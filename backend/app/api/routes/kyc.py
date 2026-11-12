"""Recipient verification (KYC). Role: recipient only.

    PUT  /recipient/kyc/identity    declared identity + both consents (encrypted before it reaches the database)
    GET  /recipient/kyc/liveness    a one-time 4-digit code for the live selfie (stateless, signed, 15 minutes)
    POST /recipient/kyc/documents   multipart upload: sanitised, malware-checked, envelope-encrypted, never returned
    POST /recipient/kyc/submit      hands the case to the assessment worker; a human still decides

Nothing here returns file contents, storage keys or hashes. The AI only recommends; approval happens in the staff console.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import AppState, limit_by_key, rate_limit, require_recipient, state
from app.api.routes.recipient import load_me
from app.core import aad, errors
from app.core.security import Session
from app.core.validation import clean_text, normalize_nic
from app.schemas.kyc import DocumentStoredOut, IdentityIn, LivenessOut, SubmitOut
from app.schemas.recipient import RecipientMeOut
from app.services.file_vault import new_object_key
from app.services.kyc import liveness
from app.services.kyc.scanner import scan_bytes
from app.services.upload_validation import UploadRejected, sanitize_kyc_upload

router = APIRouter(prefix="/recipient/kyc", tags=["kyc"], dependencies=[Depends(require_recipient)])
log = logging.getLogger("sadqah.kyc_api")

_IP_LIMIT = rate_limit("kyc-write", 60, 600)

_SAVE_IDENTITY = "SELECT api.fn_kyc_save_identity($1, $2, $3, $4, $5, $6, $7, $8)"
_REGISTER_DOC = "SELECT api.fn_kyc_register_document($1, $2, $3, $4, $5, $6)"
_SUBMIT = "SELECT api.fn_kyc_submit()"
_STATUS = "SELECT status FROM api.fn_kyc_my_status()"


@router.put("/identity", response_model=RecipientMeOut, dependencies=[Depends(_IP_LIMIT)])
async def save_identity(body: IdentityIn, session: Session = Depends(require_recipient),
                        st: AppState = Depends(state)) -> RecipientMeOut:
    await limit_by_key(st, "kyc-identity", str(session.user_id), 20, 3600)
    try:
        nic = normalize_nic(body.id_number)
    except ValueError as exc:
        raise errors.validation("Check the identity number.", {"id_number": str(exc)}) from exc
    full_name = clean_text(body.full_name, 120)
    address = clean_text(body.address, 300)
    if len(full_name) < 2 or len(address) < 5:
        raise errors.validation("Please complete every field.", {"full_name": "Enter your full legal name.",
                                                                  "address": "Enter your full address."})
    c = st.crypto
    try:
        async with st.db.api(session.user_id) as conn:
            await conn.fetchval(
                _SAVE_IDENTITY,
                c.encrypt_text(full_name, aad.KYC_FULL_NAME),
                c.encrypt_text(body.date_of_birth.isoformat(), aad.KYC_DOB),
                c.encrypt_text(nic, aad.KYC_NIC),
                c.blind_index("nic", nic),
                c.encrypt_text(address, aad.KYC_ADDRESS),
                body.doc_country.upper(),
                body.consent_biometric,
                body.consent_data)
    except asyncpg.UniqueViolationError as exc:
        raise errors.conflict("This identity document is already registered with another account. "
                              "Contact support if you think this is a mistake.") from exc
    return await load_me(st, session.user_id)


@router.get("/liveness", response_model=LivenessOut)
async def liveness_challenge(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> LivenessOut:
    await limit_by_key(st, "kyc-liveness", str(session.user_id), 20, 3600)
    challenge = liveness.issue(st.crypto, session.user_id)
    return LivenessOut(challenge_token=challenge.token, code=challenge.code,
                       expires_at=datetime.fromtimestamp(challenge.expires_at, UTC).isoformat().replace("+00:00", "Z"))


@router.post("/documents", status_code=201, response_model=DocumentStoredOut, dependencies=[Depends(_IP_LIMIT)])
async def upload_document(
    doc_type: Literal["national_id", "passport", "utility_bill", "selfie", "bank_statement", "proof_of_income"] = Form(),
    file: UploadFile = File(),
    challenge_token: str | None = Form(default=None, max_length=400),
    session: Session = Depends(require_recipient),
    st: AppState = Depends(state),
) -> DocumentStoredOut:
    await limit_by_key(st, "kyc-document", str(session.user_id), 40, 3600)

    code: str | None = None
    if doc_type == "selfie":
        code = liveness.verify(st.crypto, challenge_token or "", session.user_id)
        if code is None:
            raise errors.validation("Your selfie code has expired. Please get a new code and take the photo again.",
                                    {"challenge_token": "Missing, expired or invalid code."})

    raw = await file.read(st.settings.max_upload_bytes + 1)
    if len(raw) > st.settings.max_upload_bytes:
        raise errors.validation("That file is too large.", {"file": "Files must be 10 MB or smaller."})
    if doc_type == "selfie" and raw[:4] == b"%PDF":
        raise errors.validation("Please take a live photo, not a PDF.", {"file": "A selfie must be a photo."})
    try:
        clean = await asyncio.to_thread(sanitize_kyc_upload, raw, st.settings.max_image_pixels)
    except UploadRejected as exc:
        raise errors.validation(str(exc), {"file": str(exc)}) from exc

    if await scan_bytes(st.settings, clean.data) == "infected":
        log.warning("an uploaded KYC file failed the malware scan (user %s)", session.user_id)
        raise errors.validation("That file did not pass our security check. Please upload a different copy.",
                                {"file": "Security check failed."})

    key = new_object_key()
    wrapped = await st.vault.put_private(key, clean.data)
    if code is not None:  # the assessment worker checks that this code is visible in the selfie
        await st.vault.put_private_sidecar(key, json.dumps({"liveness_code": code}).encode())
    async with st.db.api(session.user_id) as conn:  # refused with 409 once the case is under review or approved
        await conn.fetchval(_REGISTER_DOC, doc_type, key, clean.sha256, clean.mime, clean.size, wrapped)
    return DocumentStoredOut(doc_type=doc_type, uploaded_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"))


@router.post("/submit", response_model=SubmitOut, dependencies=[Depends(_IP_LIMIT)])
async def submit(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> SubmitOut:
    await limit_by_key(st, "kyc-submit", str(session.user_id), 10, 3600)
    async with st.db.api(session.user_id) as conn:
        missing = list(await conn.fetchval(_SUBMIT) or [])
        status = await conn.fetchval(_STATUS)
    return SubmitOut(status=status, missing=missing)
