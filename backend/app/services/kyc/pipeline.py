"""KYC assessment pipeline: documents in, ADVICE for a human reviewer out.

    scan files -> read each document (vision LLM) -> compare with what the applicant declared -> estimate monthly
    income and test the "< $50 / month" distress rule -> face comparison -> fraud/consistency score -> recommended
    Exit-Poverty capital -> store via core.fn_store_kyc_assessment, which can only move the case to 'needs_human_review'.

Nothing in this module can approve or reject an applicant, and the database enforces that too.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from decimal import Decimal
from typing import Any

from app.core import aad
from app.core.config import Settings
from app.core.crypto import Crypto
from app.core.db import Database, records
from app.core.validation import normalize_nic
from app.services.file_vault import FileVault
from app.services.kyc.allocation import recommend_allocation
from app.services.kyc.extractor import DocumentExtractor
from app.services.kyc.face_match import FaceMatcher
from app.services.kyc.fraud_scoring import CaseInputs, score_case
from app.services.kyc.income_analyzer import estimate_monthly_income
from app.services.kyc.scanner import scan_bytes

log = logging.getLogger("sadqah.kyc")
RULES_VERSION = "rules-v1"


async def _load(db: Database, recipient_id: uuid.UUID):
    async with db.session("kyc") as conn:
        case = await conn.fetchrow(
            "SELECT status, full_name_enc, dob_enc, nic_number_enc, address_enc FROM core.recipients_kyc WHERE recipient_id = $1",
            recipient_id)
        docs = records(await conn.fetch(
            "SELECT id, doc_type, object_key, sha256, mime_type, wrapped_dek, scan_status, uploaded_at "
            "FROM core.kyc_documents WHERE recipient_id = $1 AND deleted_at IS NULL ORDER BY uploaded_at", recipient_id))
    return case, docs


async def process_case(db: Database, vault: FileVault, crypto: Crypto, settings: Settings,
                       extractor: DocumentExtractor, matcher: FaceMatcher, recipient_id: uuid.UUID) -> str:
    case, docs = await _load(db, recipient_id)
    if case is None or case["status"] != "processing":
        return "skipped"

    declared = {
        "name": crypto.decrypt_text(case["full_name_enc"], aad.KYC_FULL_NAME),
        "dob": crypto.decrypt_text(case["dob_enc"], aad.KYC_DOB),
        "nic": normalize_nic(crypto.decrypt_text(case["nic_number_enc"], aad.KYC_NIC)),
        "address": crypto.decrypt_text(case["address_enc"], aad.KYC_ADDRESS),
    }

    # ---- 1. fetch + scan every file -----------------------------------------------------------------------------
    blobs: dict[uuid.UUID, bytes] = {}
    infected = False
    extra_flags: list[dict[str, str]] = []
    duplicate_count = 0
    for d in docs:
        data = await vault.get_private(d["object_key"], d["wrapped_dek"])
        blobs[d["id"]] = data
        if d["scan_status"] == "pending":
            verdict = await scan_bytes(settings, data)
            async with db.session("kyc") as conn:
                await conn.execute("UPDATE core.kyc_documents SET scan_status = $1::core.scan_status WHERE id = $2",
                                   verdict, d["id"])
            if verdict == "failed":
                extra_flags.append({"code": "scan_failed", "severity": "warning",
                                    "detail": "The malware scanner was unavailable for one file."})
            d["scan_status"] = verdict
        infected = infected or d["scan_status"] == "infected"
        async with db.session("kyc") as conn:
            duplicate_count += int(await conn.fetchval(
                "SELECT count(*) FROM core.kyc_documents WHERE sha256 = $1 AND recipient_id <> $2 AND deleted_at IS NULL",
                d["sha256"], recipient_id))

    by_type: dict[str, list[dict[str, Any]]] = {}
    for d in docs:
        by_type.setdefault(d["doc_type"], []).append(d)
    id_doc = (by_type.get("national_id") or by_type.get("passport") or [None])[-1]
    bill_doc = (by_type.get("utility_bill") or [None])[-1]
    selfie_doc = (by_type.get("selfie") or [None])[-1]
    income_docs = [*(by_type.get("bank_statement") or []), *(by_type.get("proof_of_income") or [])]

    # ---- 2. read documents --------------------------------------------------------------------------------------
    income_cents: int | None = None
    face: float | None = None
    income_flags: list[dict[str, str]] = []
    inputs = CaseInputs(declared_name=declared["name"], declared_dob=declared["dob"], declared_id_number=declared["nic"],
                        declared_address=declared["address"], face_min_score=settings.kyc_face_min_score,
                        duplicate_document_count=duplicate_count, infected_document=infected)
    model_version = f"none|{RULES_VERSION}"

    if extractor.available and not infected:
        sem = asyncio.Semaphore(3)

        async def read(kind: str, doc: dict[str, Any] | None):
            if doc is None:
                return None
            async with sem:
                try:
                    return await extractor.extract(kind, blobs[doc["id"]], doc["mime_type"])
                except Exception as exc:  # noqa: BLE001  a bad reading must not sink the case; it becomes a flag
                    log.warning("could not read %s document: %s", kind, type(exc).__name__)
                    return None

        id_x, bill_x, selfie_x, *income_x = await asyncio.gather(
            read("id", id_doc), read("utility_bill", bill_doc), read("selfie", selfie_doc),
            *[read("income", d) for d in income_docs])
        inputs.id_doc, inputs.bill, inputs.selfie = id_x, bill_x, selfie_x
        inputs.income_docs = [x for x in income_x if x]

        sidecar = await vault.get_private_sidecar(selfie_doc["object_key"]) if selfie_doc else None
        if sidecar:
            inputs.expected_liveness_code = json.loads(sidecar.decode()).get("liveness_code")

        if id_doc and selfie_doc and id_doc["mime_type"] == "image/jpeg":
            face = await matcher.compare(blobs[id_doc["id"]], blobs[selfie_doc["id"]])
        inputs.face_match = face

        estimate = estimate_monthly_income(inputs.income_docs, settings.fx_rates, settings.kyc_distress_threshold_cents)
        income_cents, income_flags = estimate.monthly_usd_cents, estimate.flags
        model_version = f"{settings.kyc_llm_model}|face:{settings.kyc_face_provider}|{RULES_VERSION}"
        risk, flags = score_case(inputs)
        codes = {f["code"] for f in income_flags}
        if "income_above_threshold" in codes:
            risk += 0.2
        if "income_unreadable" in codes:
            risk += 0.1
        flags = [*income_flags, *flags]
    else:
        risk, flags = (1.0, []) if infected else (0.5, [])
        if infected:
            flags.append({"code": "infected_document", "severity": "critical", "detail": "An uploaded file failed the malware scan."})
        else:
            flags.append({"code": "ai_unavailable", "severity": "warning",
                          "detail": "Automatic document reading is not configured. The reviewer must read every document."})

    flags.extend(extra_flags)
    allocation = recommend_allocation(
        income_cents, target_monthly_cents=settings.kyc_target_monthly_income_cents,
        min_cents=settings.kyc_allocation_min_cents, max_cents=settings.kyc_allocation_max_cents,
        max_payback_months=settings.kyc_max_payback_months)
    if income_cents is not None and income_cents >= settings.kyc_distress_threshold_cents:
        allocation = None        # not eligible by the distress rule: nothing to recommend

    async with db.session("kyc") as conn:
        await conn.fetchval(
            "SELECT core.fn_store_kyc_assessment($1, $2, $3, $4, $5, $6, $7)", recipient_id, income_cents,
            None if face is None else Decimal(str(round(face, 3))), Decimal(str(round(min(1.0, risk), 3))), flags,
            allocation, model_version)
    log.info("kyc assessed recipient=%s risk=%.2f flags=%d", recipient_id, min(1.0, risk), len(flags))
    return "assessed"


async def store_failure(db: Database, recipient_id: uuid.UUID, reason: str) -> None:
    """After repeated technical failures the case goes to a human with a note, instead of waiting forever."""
    flags = [{"code": "ai_error", "severity": "warning", "detail": reason[:200]}]
    async with db.session("kyc") as conn:
        await conn.fetchval("SELECT core.fn_store_kyc_assessment($1, NULL, NULL, $2, $3, NULL, $4)", recipient_id,
                            Decimal("0.5"), flags, f"error|{RULES_VERSION}")
