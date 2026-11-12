"""Anonymous tracking and messaging for a Donation Token holder.

    POST /track/lookup     {token}        -> TrackView
    POST /track/messages   {token, body}  -> {id, status}

Privacy rules enforced here (the database enforces the rest):
  * The token is read from the POST body, normalised, hashed with the server pepper and never stored, logged or echoed.
  * A malformed, mistyped or unknown token produces the SAME 404 after the SAME amount of work (the hash is always
    computed and the lookup always runs), so the response cannot be used to probe which tokens exist.
  * Rate limits apply per client address and per token hash (the hash, not the token, is the key).
  * Messages never carry a sender identity. Bodies are screened (no contact details), then encrypted with a label bound
    to the donation, so a ciphertext cannot be replayed into another thread.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import AppState, limit_by_key, rate_limit, state
from app.api.routes.public import iso, media_url
from app.core import aad, errors
from app.core.crypto import CryptoError
from app.core.validation import clean_text
from app.schemas.tracking import (
    TrackCampaignOut,
    TrackDonationOut,
    TrackGratitudeOut,
    TrackLookupIn,
    TrackMessageIn,
    TrackMessageOut,
    TrackMessagePostedOut,
    TrackRecipientOut,
    TrackUpdateOut,
    TrackViewOut,
)
from app.services.moderation import screen_text
from app.services.token_service import normalise_token

router = APIRouter(prefix="", tags=["tracking"])
log = logging.getLogger("sadqah.tracking")

_LOOKUP_IP_LIMIT = rate_limit("track-lookup", 40, 600)
_MESSAGE_IP_LIMIT = rate_limit("track-message", 10, 600)

_TRACK = (
    "SELECT donation_id, amount_cents, donation_status, delivery_state, thread_open, given_at, campaign_slug, campaign_title, "
    "recipient_slug, recipient_name, region_country, region_admin1, gratitude_body, gratitude_at FROM api.fn_track_donation($1)"
)
_TRACK_UPDATES = "SELECT id, body, media_object_keys, visibility, created_at FROM api.fn_track_updates($1)"
_TRACK_THREAD = "SELECT id, sender, body_enc, moderation_status, created_at FROM api.fn_track_thread($1)"
_MARK_READ = "SELECT api.fn_donor_mark_read($1)"
_POST_MESSAGE = "SELECT api.fn_donor_post_message($1, $2)"
_APPROVE_MESSAGE = "SELECT core.fn_moderate_message($1, 'approved', 'automatic screening passed', $2)"


def _not_found() -> errors.ApiError:
    return errors.not_found("We could not find a gift for that token. Check it and try again.")


def _token_hash(st: AppState, raw: str) -> tuple[bytes, bool]:
    """(hash, well_formed). An unusable token is hashed too, so both outcomes cost the same."""
    payload = normalise_token(raw)
    return st.crypto.hash_token(payload if payload is not None else "invalid\x00" + raw[:120]), payload is not None


async def approve_if_configured(st: AppState, message_id: uuid.UUID) -> str:
    """Messages that pass screening are approved automatically when a system moderator account is configured;
    otherwise they wait in the staff moderation queue."""
    raw = st.settings.system_moderator_user_id
    if not raw:
        return "pending"
    try:
        moderator = uuid.UUID(raw)
    except ValueError:
        log.error("SYSTEM_MODERATOR_USER_ID is not a valid UUID; messages stay pending")
        return "pending"
    async with st.db.session("admin", moderator) as conn:
        await conn.fetchval(_APPROVE_MESSAGE, message_id, moderator)
    return "approved"


@router.post("/track/lookup", response_model=TrackViewOut, dependencies=[Depends(_LOOKUP_IP_LIMIT)])
async def lookup(body: TrackLookupIn, st: AppState = Depends(state)) -> TrackViewOut:
    digest, well_formed = _token_hash(st, body.token)
    await limit_by_key(st, "track-token", digest.hex(), 60, 600)

    async with st.db.api() as conn:
        rows = await conn.fetch(_TRACK, digest)
        if not rows or not well_formed:
            raise _not_found()
        gift = rows[0]
        updates = await conn.fetch(_TRACK_UPDATES, digest)
        thread = await conn.fetch(_TRACK_THREAD, digest)
        await conn.fetchval(_MARK_READ, digest)

    donation_id = gift["donation_id"]
    messages: list[TrackMessageOut] = []
    for m in thread:
        try:
            text = st.crypto.decrypt_text(m["body_enc"], aad.message(donation_id))
        except CryptoError:
            log.error("a stored message could not be decrypted (message %s)", m["id"])
            continue
        messages.append(TrackMessageOut(id=str(m["id"]), sender=m["sender"], body=text, status=m["moderation_status"],
                                        created_at=iso(m["created_at"])))
    return TrackViewOut(
        donation=TrackDonationOut(
            amount_cents=int(gift["amount_cents"]), given_at=gift["given_at"].isoformat(), status=gift["donation_status"],
            delivery_state=gift["delivery_state"], thread_open=bool(gift["thread_open"]),
        ),
        campaign=TrackCampaignOut(slug=gift["campaign_slug"], title=gift["campaign_title"]),
        recipient=TrackRecipientOut(slug=gift["recipient_slug"], name=gift["recipient_name"],
                                    region_country=gift["region_country"], region_admin1=gift["region_admin1"]),
        updates=[
            TrackUpdateOut(id=str(u["id"]), body=u["body"], media_urls=[media_url(k) for k in (u["media_object_keys"] or [])],
                           visibility=u["visibility"], created_at=iso(u["created_at"]))
            for u in updates
        ],
        messages=messages,
        gratitude=TrackGratitudeOut(body=gift["gratitude_body"], created_at=iso(gift["gratitude_at"]))
        if gift["gratitude_body"] is not None else None,
    )


@router.post("/track/messages", status_code=201, response_model=TrackMessagePostedOut,
             dependencies=[Depends(_MESSAGE_IP_LIMIT)])
async def post_message(body: TrackMessageIn, st: AppState = Depends(state)) -> TrackMessagePostedOut:
    digest, well_formed = _token_hash(st, body.token)
    await limit_by_key(st, "track-message-token", digest.hex(), 20, 600)

    async with st.db.api() as conn:
        rows = await conn.fetch(_TRACK, digest)
    if not rows or not well_formed:
        raise _not_found()
    gift = rows[0]
    if not gift["thread_open"]:
        raise errors.conflict("You can message the recipient once your gift has been delivered.")

    text = clean_text(body.body, 1000)
    verdict = screen_text(text, max_len=1000)
    if not verdict.allowed:
        raise errors.ApiError(422, "message_rejected", verdict.reason or "That message could not be sent.")

    ciphertext = st.crypto.encrypt_text(text, aad.message(gift["donation_id"]))
    async with st.db.api() as conn:
        message_id = await conn.fetchval(_POST_MESSAGE, digest, ciphertext)
    status = await approve_if_configured(st, message_id)
    return TrackMessagePostedOut(id=str(message_id), status=status)  # type: ignore[arg-type]
