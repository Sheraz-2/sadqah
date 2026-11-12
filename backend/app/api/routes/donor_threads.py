"""A signed-in donor's private conversations about their PUBLIC gifts.

    GET  /me/threads                          -> the donor's captured and delivered public gifts, with unread counts
    GET  /me/threads/{donation_id}            -> one conversation (marks approved recipient replies as read)
    POST /me/threads/{donation_id}/messages   {body} -> {id, status}

This is the authenticated twin of the token door in tracking.py: same table, same donation-bound encryption, same screening,
same moderation and limits. Anonymous gifts have no donor id, so they can never appear here; they keep using /track.
Ownership is decided by the database from the session identity (core.current_user_id()), never by a client-supplied id: a donation
that is not the caller's is indistinguishable from one that does not exist.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import AppState, limit_by_key, require_roles, state
from app.api.routes.public import iso
from app.api.routes.tracking import approve_if_configured
from app.core import aad, errors
from app.core.crypto import CryptoError
from app.core.security import Session
from app.core.validation import clean_text
from app.schemas.donor_threads import (
    DonorMessageIn,
    DonorMessageOut,
    DonorMessagePostedOut,
    DonorThreadListOut,
    DonorThreadOut,
    DonorThreadViewOut,
)
from app.services.moderation import screen_text

require_donor = require_roles("donor")
router = APIRouter(prefix="/me", tags=["donor-threads"], dependencies=[Depends(require_donor)])
log = logging.getLogger("sadqah.donor_threads")

_THREADS = ("SELECT donation_id, campaign_slug, campaign_title, recipient_name, donation_status, thread_open, paid_out_at, "
            "last_message_at, unread_count FROM api.fn_my_threads()")
_THREAD_MESSAGES = "SELECT id, sender, body_enc, moderation_status, created_at FROM api.fn_my_thread_messages($1)"
_MARK_READ = "SELECT api.fn_my_mark_read($1)"
_POST = "SELECT api.fn_my_post_message($1, $2)"


def _thread_out(r) -> DonorThreadOut:
    return DonorThreadOut(
        donation_id=str(r["donation_id"]), campaign_slug=r["campaign_slug"], campaign_title=r["campaign_title"],
        recipient_name=r["recipient_name"], donation_status=r["donation_status"], thread_open=bool(r["thread_open"]),
        paid_out_at=iso(r["paid_out_at"]) if r["paid_out_at"] else None,
        last_message_at=iso(r["last_message_at"]) if r["last_message_at"] else None,
        unread_count=int(r["unread_count"]))


def _mine(rows, donation_id: uuid.UUID):
    """The caller's own thread row, or a plain 404: whether the id exists for someone else is never revealed."""
    for r in rows:
        if r["donation_id"] == donation_id:
            return r
    raise errors.not_found("We could not find that conversation.")


@router.get("/threads", response_model=DonorThreadListOut)
async def my_threads(session: Session = Depends(require_donor), st: AppState = Depends(state)) -> DonorThreadListOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_THREADS)
    return DonorThreadListOut(items=[_thread_out(r) for r in rows])


@router.get("/threads/{donation_id}", response_model=DonorThreadViewOut)
async def my_thread(donation_id: uuid.UUID, session: Session = Depends(require_donor),
                    st: AppState = Depends(state)) -> DonorThreadViewOut:
    async with st.db.api(session.user_id) as conn:
        thread = _mine(await conn.fetch(_THREADS), donation_id)
        rows = await conn.fetch(_THREAD_MESSAGES, donation_id)
        await conn.fetchval(_MARK_READ, donation_id)
    out: list[DonorMessageOut] = []
    for m in rows:
        try:
            text = st.crypto.decrypt_text(m["body_enc"], aad.message(donation_id))
        except CryptoError:
            log.error("a stored message could not be decrypted (message %s)", m["id"])
            continue
        out.append(DonorMessageOut(id=str(m["id"]), sender=m["sender"], body=text, status=m["moderation_status"],
                                   created_at=iso(m["created_at"])))
    view = _thread_out(thread)
    view.unread_count = 0  # the approved replies in `messages` have just been read
    return DonorThreadViewOut(thread=view, messages=out)


@router.post("/threads/{donation_id}/messages", status_code=201, response_model=DonorMessagePostedOut)
async def my_post_message(donation_id: uuid.UUID, body: DonorMessageIn, session: Session = Depends(require_donor),
                          st: AppState = Depends(state)) -> DonorMessagePostedOut:
    await limit_by_key(st, "donor-message", str(session.user_id), 30, 3600)
    async with st.db.api(session.user_id) as conn:
        thread = _mine(await conn.fetch(_THREADS), donation_id)
    if not thread["thread_open"]:
        raise errors.conflict("Messaging will open once your gift has been delivered.")

    text = clean_text(body.body, 1000)
    verdict = screen_text(text)
    if not verdict.allowed:
        raise errors.validation(verdict.reason or "Please rewrite your message.", {"body": verdict.reason or "Not allowed."})

    ciphertext = st.crypto.encrypt_text(text, aad.message(donation_id))
    async with st.db.api(session.user_id) as conn:  # not yours -> 404; 10 per day per thread -> 429; not delivered -> 409 (trigger)
        message_id = await conn.fetchval(_POST, donation_id, ciphertext)
    status = await approve_if_configured(st, message_id)
    return DonorMessagePostedOut(id=str(message_id), status=status)  # type: ignore[arg-type]
