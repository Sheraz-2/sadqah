"""Recipient portal: profile, payout destination, public switch, campaign, updates, gifts, messages and thank-yous.
KYC (identity, liveness, documents, submit) lives in kyc.py. Role: recipient only.

    POST /recipient/profile            GET /recipient/me           PUT /recipient/profile
    PUT  /recipient/payout             POST /recipient/profile/public
    POST /recipient/campaign           POST /recipient/updates (multipart)
    GET  /recipient/donations          GET /recipient/threads[/{id}]   POST /recipient/threads/{id}/messages
    POST /recipient/gratitude

Privacy: donors' identities never reach this module. The database labels every donor ("A SadQah donor") and truncates the
timestamps of anonymous gifts; the audience of a thank-you is chosen by the server from the donor's own choice.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile

from app.api.deps import AppState, limit_by_key, rate_limit, require_recipient, state
from app.api.routes.public import iso
from app.api.routes.tracking import approve_if_configured
from app.core import aad, errors
from app.core.crypto import CryptoError
from app.core.security import Session
from app.core.validation import clean_text, mask_handle, normalize_email, normalize_phone, slugify
from app.schemas.recipient import (
    BalanceOut,
    CampaignCreateIn,
    GratitudeIn,
    GratitudePostedOut,
    KindWordOut,
    KindWordsOut,
    KycDocumentOut,
    KycStateOut,
    MessageIn,
    MessagePostedOut,
    MyCampaignOut,
    PayoutIn,
    PayoutOut,
    ProfileCreateIn,
    ProfileOut,
    ProfileUpdateIn,
    PublicIn,
    RecipientDonationOut,
    RecipientDonationsOut,
    RecipientMeOut,
    ThreadListOut,
    ThreadMessageOut,
    ThreadOut,
    ThreadViewOut,
    UpdatePostedOut,
)
from app.services.file_vault import new_object_key
from app.services.kyc.requirements import missing_requirements
from app.services.moderation import screen_text
from app.services.upload_validation import UploadRejected, sanitize_public_image

router = APIRouter(prefix="/recipient", tags=["recipient"], dependencies=[Depends(require_recipient)])
log = logging.getLogger("sadqah.recipient")

_PROFILE_IP_LIMIT = rate_limit("recipient-write", 60, 600)

MAX_IMAGES = 4
_PROFILE = ("SELECT slug, public_name, story, business_type, region_country, region_admin1, profile_public "
            "FROM api.my_recipient_profile")
_KYC = "SELECT status, rejection_reason, approved_allocation_cents, identity_saved, documents FROM api.fn_kyc_my_status()"
_PAYOUT = "SELECT receiver_type, receiver_enc FROM api.fn_my_payout()"
_CAMPAIGN = ("SELECT slug, title, goal_cents, raised_cents, paid_out_cents, status FROM api.my_campaign "
             "ORDER BY created_at DESC LIMIT 1")
_BALANCE = ("SELECT raised_cents, queued_cents, in_flight_cents, unclaimed_cents, delivered_cents, problem_cents "
            "FROM api.fn_recipient_balance()")
_CREATE_PROFILE = "SELECT api.fn_create_recipient_profile($1, $2, $3, $4, $5, $6, $7, $8, $9)"
_UPDATE_PROFILE = "SELECT api.fn_update_recipient_profile($1, $2, $3, $4)"
_SET_RECEIVER = "SELECT api.fn_set_payout_receiver($1, $2, $3)"
_SET_PUBLIC = "SELECT api.fn_set_profile_public($1)"
_CREATE_CAMPAIGN = "SELECT api.fn_create_campaign($1, $2, $3, $4)"
_POST_UPDATE = "SELECT api.fn_post_campaign_update($1, $2, $3)"
_DONATIONS = ("SELECT donation_id, campaign_slug, is_anonymous, donor_label, amount_cents, delivery_state, captured_at, "
              "paid_out_at, has_gratitude FROM api.fn_recipient_donations()")
_THREADS = ("SELECT thread_id, donor_label, amount_cents, paid_out_at, last_message_at, unread_count "
            "FROM api.fn_recipient_threads()")
_THREAD_MESSAGES = "SELECT id, sender, body_enc, moderation_status, created_at FROM api.fn_recipient_thread_messages($1)"
_THREAD_MARK_READ = "SELECT api.fn_recipient_mark_read($1)"
_THREAD_POST = "SELECT api.fn_recipient_post_message($1, $2)"
# Kind words on the recipient's OWN campaigns. Same data source the public campaign page uses (approved comments only, on public
# campaigns); ownership comes from api.my_campaign, which the database scopes to the signed-in user. No id is taken from the client.
_KIND_WORDS = ("SELECT cm.id, cm.campaign_slug, cm.author_name, cm.body, cm.created_at FROM api.public_campaign_comments cm "
               "WHERE cm.campaign_slug IN (SELECT slug FROM api.my_campaign) ORDER BY cm.created_at DESC LIMIT 100")
_POST_GRATITUDE = "SELECT api.fn_post_gratitude($1, $2)"
_APPROVE_GRATITUDE = "SELECT core.fn_moderate_gratitude($1, 'approved', $2)"


# --------------------------------------------------------------------------- shared
async def load_me(st: AppState, user_id: uuid.UUID) -> RecipientMeOut:
    """Everything the portal needs in one read. Used by every route here and by kyc.py."""
    async with st.db.api(user_id) as conn:
        profile = await conn.fetchrow(_PROFILE)
        if profile is None:
            return RecipientMeOut(profile=None, kyc=None, payout=None, campaign=None, balance=None)
        kyc = await conn.fetchrow(_KYC)
        payout = await conn.fetchrow(_PAYOUT)
        campaign = await conn.fetchrow(_CAMPAIGN)
        balance = await conn.fetchrow(_BALANCE)

    kyc_out = None
    if kyc is not None:
        docs = list(kyc["documents"] or [])
        kyc_out = KycStateOut(
            status=kyc["status"],
            rejection_reason=kyc["rejection_reason"],
            approved_allocation_cents=None if kyc["approved_allocation_cents"] is None else int(kyc["approved_allocation_cents"]),
            identity_saved=bool(kyc["identity_saved"]),
            documents=[KycDocumentOut(doc_type=d["doc_type"], uploaded_at=d["uploaded_at"], scan_status=d["scan_status"])
                       for d in docs],
            missing=missing_requirements(bool(kyc["identity_saved"]), docs),  # type: ignore[arg-type]
        )
    payout_out = None
    if payout is not None:
        try:
            handle = st.crypto.decrypt_text(payout["receiver_enc"], aad.RECEIVER)
            payout_out = PayoutOut(type=payout["receiver_type"], handle_masked=mask_handle(payout["receiver_type"], handle))
        except CryptoError:
            log.error("a payout destination could not be decrypted")
    return RecipientMeOut(
        profile=ProfileOut(**{k: profile[k] for k in ProfileOut.model_fields}),
        kyc=kyc_out,
        payout=payout_out,
        campaign=MyCampaignOut(**{k: (int(campaign[k]) if k.endswith("_cents") else campaign[k])
                                  for k in MyCampaignOut.model_fields}) if campaign is not None else None,
        balance=BalanceOut(**{k: int(balance[k]) for k in BalanceOut.model_fields}) if balance is not None else None,
    )


def prepare_receiver(st: AppState, payout_type: Literal["EMAIL", "PHONE"], handle: str) -> tuple[bytes, bytes]:
    """Validates the PayPal destination and returns (encrypted handle, blind index)."""
    try:
        if payout_type == "EMAIL":
            normal = normalize_email(handle)
        else:
            if not st.settings.paypal_allows_phone_receivers:
                raise errors.validation("That payout type is not available yet.", {
                    "payout_type": "Phone payouts are not available in the PayPal sandbox. Use an e-mail address."})
            normal = normalize_phone(handle)
    except ValueError as exc:
        raise errors.validation("Check the payout details.", {"payout_handle": str(exc)}) from exc
    return st.crypto.encrypt_text(normal, aad.RECEIVER), st.crypto.blind_index("receiver", normal)


def _unique_conflict(exc: asyncpg.UniqueViolationError) -> errors.ApiError:
    name = exc.constraint_name or ""
    if "blind_idx" in name:
        return errors.conflict("That PayPal address is already linked to another SadQah account.")
    if "user_id" in name:
        return errors.conflict("You already have a profile.")
    return errors.conflict("That already exists.")


# --------------------------------------------------------------------------- profile
@router.get("/me", response_model=RecipientMeOut)
async def me(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> RecipientMeOut:
    return await load_me(st, session.user_id)


@router.post("/profile", status_code=201, response_model=RecipientMeOut, dependencies=[Depends(_PROFILE_IP_LIMIT)])
async def create_profile(body: ProfileCreateIn, session: Session = Depends(require_recipient),
                         st: AppState = Depends(state)) -> RecipientMeOut:
    name = clean_text(body.public_name, 60)
    if len(name) < 2:
        raise errors.validation("Check your name.", {"public_name": "Enter the name you want donors to see."})
    receiver_enc, receiver_idx = prepare_receiver(st, body.payout_type, body.payout_handle)
    try:
        async with st.db.api(session.user_id) as conn:
            await conn.fetchval(
                _CREATE_PROFILE, slugify(name), name, clean_text(body.story, 4000), clean_text(body.business_type or "", 80) or None,
                body.region_country.upper(), clean_text(body.region_admin1 or "", 80) or None, body.payout_type,
                receiver_enc, receiver_idx)
    except asyncpg.UniqueViolationError as exc:
        raise _unique_conflict(exc) from exc
    return await load_me(st, session.user_id)


@router.put("/profile", response_model=RecipientMeOut, dependencies=[Depends(_PROFILE_IP_LIMIT)])
async def update_profile(body: ProfileUpdateIn, session: Session = Depends(require_recipient),
                         st: AppState = Depends(state)) -> RecipientMeOut:
    async with st.db.api(session.user_id) as conn:
        await conn.fetchval(
            _UPDATE_PROFILE,
            clean_text(body.public_name, 60) if body.public_name is not None else None,
            clean_text(body.story, 4000) if body.story is not None else None,
            clean_text(body.business_type, 80) if body.business_type is not None else None,
            clean_text(body.region_admin1, 80) if body.region_admin1 is not None else None)
    return await load_me(st, session.user_id)


@router.put("/payout", response_model=RecipientMeOut, dependencies=[Depends(_PROFILE_IP_LIMIT)])
async def set_payout(body: PayoutIn, session: Session = Depends(require_recipient),
                     st: AppState = Depends(state)) -> RecipientMeOut:
    await limit_by_key(st, "payout-change", str(session.user_id), 5, 3600)
    receiver_enc, receiver_idx = prepare_receiver(st, body.payout_type, body.payout_handle)
    try:
        async with st.db.api(session.user_id) as conn:
            await conn.fetchval(_SET_RECEIVER, body.payout_type, receiver_enc, receiver_idx)
    except asyncpg.UniqueViolationError as exc:
        raise _unique_conflict(exc) from exc
    return await load_me(st, session.user_id)


@router.post("/profile/public", response_model=RecipientMeOut, dependencies=[Depends(_PROFILE_IP_LIMIT)])
async def set_public(body: PublicIn, session: Session = Depends(require_recipient),
                     st: AppState = Depends(state)) -> RecipientMeOut:
    async with st.db.api(session.user_id) as conn:  # the database refuses publication before KYC approval (409)
        await conn.fetchval(_SET_PUBLIC, body.public)
    return await load_me(st, session.user_id)


# --------------------------------------------------------------------------- campaign and updates
@router.post("/campaign", status_code=201, response_model=RecipientMeOut, dependencies=[Depends(_PROFILE_IP_LIMIT)])
async def create_campaign(body: CampaignCreateIn, session: Session = Depends(require_recipient),
                          st: AppState = Depends(state)) -> RecipientMeOut:
    title = clean_text(body.title, 120)
    if len(title) < 3:
        raise errors.validation("Check the title.", {"title": "Give your campaign a short title."})
    try:
        async with st.db.api(session.user_id) as conn:  # approved KYC and goal <= allocation are enforced by the database
            await conn.fetchval(_CREATE_CAMPAIGN, slugify(title, 60), title, clean_text(body.story, 4000), body.goal_cents)
    except asyncpg.UniqueViolationError as exc:
        raise errors.conflict("You already have a live campaign.") from exc
    return await load_me(st, session.user_id)


@router.post("/updates", status_code=201, response_model=UpdatePostedOut)
async def post_update(
    body: str = Form(min_length=1, max_length=4000),
    visibility: Literal["public", "donors"] = Form("public"),
    images: list[UploadFile] = File(default_factory=list),
    session: Session = Depends(require_recipient),
    st: AppState = Depends(state),
) -> UpdatePostedOut:
    await limit_by_key(st, "campaign-update", str(session.user_id), 20, 3600)
    text = clean_text(body, 4000)
    verdict = screen_text(text, max_len=4000)
    if not verdict.allowed:
        raise errors.validation(verdict.reason or "Please rewrite your update.", {"body": verdict.reason or "Not allowed."})
    if len(images) > MAX_IMAGES:
        raise errors.validation(f"You can attach up to {MAX_IMAGES} photos.", {"images": f"At most {MAX_IMAGES} photos."})

    keys: list[str] = []
    cleaned = []
    for image in images:
        raw = await image.read(st.settings.max_upload_bytes + 1)
        if len(raw) > st.settings.max_upload_bytes:
            raise errors.validation("That photo is too large.", {"images": "Each photo must be under 10 MB."})
        try:
            cleaned.append(await asyncio.to_thread(sanitize_public_image, raw, st.settings.max_image_pixels))
        except UploadRejected as exc:
            raise errors.validation(str(exc), {"images": str(exc)}) from exc
    for c in cleaned:
        key = new_object_key("webp")
        await st.vault.put_public(key, c.data)
        keys.append(key)

    async with st.db.api(session.user_id) as conn:
        update_id = await conn.fetchval(_POST_UPDATE, text, keys, visibility)
    return UpdatePostedOut(id=str(update_id))


# --------------------------------------------------------------------------- gifts
@router.get("/donations", response_model=RecipientDonationsOut)
async def donations(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> RecipientDonationsOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_DONATIONS)
    return RecipientDonationsOut(items=[
        RecipientDonationOut(
            donation_id=str(r["donation_id"]), campaign_slug=r["campaign_slug"], donor_label=r["donor_label"],
            is_anonymous=bool(r["is_anonymous"]), amount_cents=int(r["amount_cents"]), delivery_state=r["delivery_state"],
            captured_at=iso(r["captured_at"]), paid_out_at=iso(r["paid_out_at"]) if r["paid_out_at"] else None,
            has_gratitude=bool(r["has_gratitude"]))
        for r in rows])


# --------------------------------------------------------------------------- kind words (public comments on my campaigns)
@router.get("/kind-words", response_model=KindWordsOut)
async def kind_words(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> KindWordsOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_KIND_WORDS)
    return KindWordsOut(items=[
        KindWordOut(id=str(r["id"]), campaign_slug=r["campaign_slug"], author_name=r["author_name"], body=r["body"],
                    created_at=iso(r["created_at"]))
        for r in rows])


# --------------------------------------------------------------------------- threads
@router.get("/threads", response_model=ThreadListOut)
async def threads(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> ThreadListOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_THREADS)
    return ThreadListOut(items=[
        ThreadOut(thread_id=str(r["thread_id"]), donor_label=r["donor_label"], amount_cents=int(r["amount_cents"]),
                  paid_out_at=iso(r["paid_out_at"]) if r["paid_out_at"] else None,
                  last_message_at=iso(r["last_message_at"]) if r["last_message_at"] else None,
                  unread_count=int(r["unread_count"]))
        for r in rows])


@router.get("/threads/{thread_id}", response_model=ThreadViewOut)
async def thread(thread_id: uuid.UUID, session: Session = Depends(require_recipient),
                 st: AppState = Depends(state)) -> ThreadViewOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_THREAD_MESSAGES, thread_id)
        await conn.fetchval(_THREAD_MARK_READ, thread_id)
    out: list[ThreadMessageOut] = []
    for m in rows:
        try:
            text = st.crypto.decrypt_text(m["body_enc"], aad.message(thread_id))
        except CryptoError:
            log.error("a stored message could not be decrypted (message %s)", m["id"])
            continue
        out.append(ThreadMessageOut(id=str(m["id"]), sender=m["sender"], body=text, status=m["moderation_status"],
                                    created_at=iso(m["created_at"])))
    return ThreadViewOut(messages=out)


@router.post("/threads/{thread_id}/messages", status_code=201, response_model=MessagePostedOut)
async def post_message(thread_id: uuid.UUID, body: MessageIn, session: Session = Depends(require_recipient),
                       st: AppState = Depends(state)) -> MessagePostedOut:
    await limit_by_key(st, "recipient-message", str(session.user_id), 30, 3600)
    text = clean_text(body.body, 1000)
    verdict = screen_text(text)
    if not verdict.allowed:
        raise errors.validation(verdict.reason or "Please rewrite your message.", {"body": verdict.reason or "Not allowed."})
    async with st.db.api(session.user_id) as conn:  # unknown thread / not yours -> 404; 10 per day per thread -> 429
        message_id = await conn.fetchval(_THREAD_POST, thread_id, st.crypto.encrypt_text(text, aad.message(thread_id)))
    status = await approve_if_configured(st, message_id)
    return MessagePostedOut(id=str(message_id), status=status)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- gratitude
@router.post("/gratitude", status_code=201, response_model=GratitudePostedOut)
async def post_gratitude(body: GratitudeIn, session: Session = Depends(require_recipient),
                         st: AppState = Depends(state)) -> GratitudePostedOut:
    await limit_by_key(st, "gratitude", str(session.user_id), 40, 3600)
    text = clean_text(body.body, 1000)
    verdict = screen_text(text)
    if not verdict.allowed:
        raise errors.validation(verdict.reason or "Please rewrite your thank-you.", {"body": verdict.reason or "Not allowed."})
    async with st.db.api(session.user_id) as conn:
        gifts = await conn.fetch(_DONATIONS)
        gift = next((g for g in gifts if g["donation_id"] == body.donation_id), None)
        if gift is None:
            raise errors.not_found("We could not find that gift.")
        # The audience is the donor's own choice, not the recipient's: public donors are thanked directly, anonymous
        # donors as part of the community. The database trigger enforces the same rule.
        note_id = await conn.fetchval(_POST_GRATITUDE, body.donation_id, text)
    status = await _approve_gratitude(st, note_id)
    return GratitudePostedOut(id=str(note_id), audience="community" if gift["is_anonymous"] else "donor", status=status)


async def _approve_gratitude(st: AppState, note_id: uuid.UUID) -> Literal["approved", "pending"]:
    raw = st.settings.system_moderator_user_id
    if not raw:
        return "pending"
    try:
        moderator = uuid.UUID(raw)
    except ValueError:
        return "pending"
    async with st.db.session("admin", moderator) as conn:
        await conn.fetchval(_APPROVE_GRATITUDE, note_id, moderator)
    return "approved"
