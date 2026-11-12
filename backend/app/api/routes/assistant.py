"""The SadQah assistant.

    POST /assistant/chat         anyone: a guide that helps people who are stuck, in their own language
    POST /assistant/price-check  recipients: local-market price estimates for a list of needs (nothing is stored)
    POST /assistant/needs        recipients: submit the list with proof (photo or PDF); the proof is checked and the case goes to staff
    GET  /assistant/needs        recipients: my submitted lists and their outcome

The assistant advises and a person decides: nothing here approves, rejects or pays. Model output is coerced into a fixed
shape (app.services.assistant), estimates are always labelled as estimates, and the proof file is re-encoded, scanned and
stored in the encrypted vault exactly like a verification document.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import ValidationError

from app.api.deps import AppState, limit_by_key, optional_session, rate_limit, require_recipient, state
from app.api.routes.recipient import load_me
from app.core import errors
from app.core.security import Session
from app.core.validation import clean_text
from app.schemas.assistant import (
    ChatOut,
    ChatRequest,
    NeedsIn,
    NeedsListOut,
    NeedsRequestOut,
    NeedsSubmittedOut,
    PriceCheckOut,
)
from app.services.assistant import (
    NOT_CHECKED,
    AskedItem,
    Assistant,
    evaluate_items,
    faq_answer,
    normalize_history,
    route_priority,
    stamp,
    summarize,
    unsupported_answer,
)
from app.services.file_vault import new_object_key
from app.services.kyc.scanner import scan_bytes
from app.services.upload_validation import UploadRejected, sanitize_kyc_upload

router = APIRouter(prefix="/assistant", tags=["assistant"])
log = logging.getLogger("sadqah.assistant_api")

_CHAT_IP = rate_limit("assistant-chat", 40, 600)
_CHAT_DAY = rate_limit("assistant-chat-day", 250, 86400)
_NEEDS_IP = rate_limit("assistant-needs", 30, 600)

_SUBMIT = "SELECT api.fn_needs_submit($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)"
_LIST = ("SELECT id, status, country, local_currency, items, requested_total_cents, estimated_total_cents, has_proof, "
         "reviewer_note, created_at FROM api.fn_needs_list()")

DISCLAIMER = ("These are estimates of typical local prices from an AI model, not quotes and not facts. A person at SadQah reviews "
              "every request and may ask for a receipt or supplier quote.")

_assistant: Assistant | None = None


def assistant_for(st: AppState) -> Assistant:
    global _assistant
    if _assistant is None:
        _assistant = Assistant(st.settings)
    return _assistant


def _iso(value: Any) -> str:
    return value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)


# --------------------------------------------------------------------------------------------- chat
@router.post("/chat", response_model=ChatOut, dependencies=[Depends(_CHAT_IP), Depends(_CHAT_DAY)])
async def chat(body: ChatRequest, session: Session | None = Depends(optional_session), st: AppState = Depends(state)) -> ChatOut:
    if session is not None:
        await limit_by_key(st, "assistant-chat-user", str(session.user_id), 80, 3600)
    # One normalisation point for every engine: valid alternation, bounded size (see normalize_history). A history that merely starts
    # or ends oddly (e.g. a window cut in the middle of a conversation) is repaired, not rejected.
    msgs = normalize_history([{"role": m.role, "content": m.content} for m in body.messages],
                             max_messages=st.settings.assistant_history_messages, max_chars=st.settings.assistant_history_chars)
    if not msgs:
        raise errors.validation("Please type a message first.")
    asked = msgs[-1]["content"]
    if (fixed := unsupported_answer(asked)) is not None:
        return ChatOut(reply=fixed, ai=False)
    bot = assistant_for(st)
    if not bot.available:
        return ChatOut(reply=faq_answer(asked), ai=False)
    try:
        reply = await bot.chat(msgs, role=session.role if session else "guest", page=body.page)
    except Exception as exc:  # busy, network, quota, model error: never show a stack trace, and never log what was said
        log.warning("assistant chat failed (%s)", type(exc).__name__)
        return ChatOut(reply=faq_answer(asked, ai_failed=True), ai=False)
    return ChatOut(reply=reply, ai=True)


# --------------------------------------------------------------------------------------------- needs helpers
async def _price(st: AppState, *, country: str, currency: str, business: str | None, note: str, items: list[Any],
                 allocation: int | None) -> tuple[list[Any], dict[str, Any], bool]:
    asked = [AskedItem(name=clean_text(i.name, 120), quantity=float(i.quantity), asked_unit_price=float(i.asked_price)) for i in items]
    bot = assistant_for(st)
    rate, estimates, ok = None, {}, False
    if bot.available:
        try:
            rate, estimates = await bot.estimate_prices(country=country, currency=currency, business_type=business, asked=asked, note=note)
            ok = bool(estimates)
        except Exception as exc:
            log.warning("price estimate failed (%s)", type(exc).__name__)
    results = evaluate_items(asked, estimates)
    return results, summarize(results, rate if ok else None, allocation), ok


async def _recipient_context(st: AppState, session: Session) -> tuple[str, str | None, int | None]:
    me = await load_me(st, session.user_id)
    if me.profile is None:
        raise errors.ApiError(409, "profile_required", "Create your profile first, then come back here.")
    alloc = me.kyc.approved_allocation_cents if me.kyc else None
    return me.profile.region_country.upper(), me.profile.business_type, alloc


# --------------------------------------------------------------------------------------------- price check
@router.post("/price-check", response_model=PriceCheckOut, dependencies=[Depends(_NEEDS_IP)])
async def price_check(body: NeedsIn, session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> PriceCheckOut:
    await limit_by_key(st, "assistant-price", str(session.user_id), 30, 3600)
    country, business, alloc = await _recipient_context(st, session)
    results, summary, ok = await _price(st, country=country, currency=body.currency.upper(), business=business,
                                        note=body.explanation, items=body.items, allocation=alloc)
    return PriceCheckOut(ai_available=ok, country=country, currency=body.currency.upper(), items=[r.as_dict() for r in results],
                         summary=summary, disclaimer=DISCLAIMER)


# --------------------------------------------------------------------------------------------- submit
@router.post("/needs", status_code=201, response_model=NeedsSubmittedOut, dependencies=[Depends(_NEEDS_IP)])
async def submit_needs(
    payload: str = Form(max_length=20_000),
    proof: UploadFile = File(),
    session: Session = Depends(require_recipient),
    st: AppState = Depends(state),
) -> NeedsSubmittedOut:
    await limit_by_key(st, "assistant-submit", str(session.user_id), 6, 3600)
    try:
        body = NeedsIn.model_validate(json.loads(payload))
    except (ValueError, ValidationError) as exc:
        raise errors.validation("Please check your list.", {"items": "Each item needs a name, a quantity and a price."}) from exc

    raw = await proof.read(st.settings.max_upload_bytes + 1)
    if len(raw) > st.settings.max_upload_bytes:
        raise errors.validation("That file is too large.", {"proof": "Files must be 10 MB or smaller."})
    try:
        clean = await asyncio.to_thread(sanitize_kyc_upload, raw, st.settings.max_image_pixels)
    except UploadRejected as exc:
        raise errors.validation(str(exc), {"proof": str(exc)}) from exc
    if await scan_bytes(st.settings, clean.data) == "infected":
        log.warning("a needs-proof upload failed the malware scan (user %s)", session.user_id)
        raise errors.validation("That file did not pass our security check. Please upload a different copy.", {"proof": "Security check failed."})

    country, business, alloc = await _recipient_context(st, session)
    currency = body.currency.upper()
    names = "; ".join(f"{clean_text(i.name, 60)} x{i.quantity:g}" for i in body.items)[:400]
    bot = assistant_for(st)

    async def proof_check() -> dict[str, Any]:
        if not bot.can_review_images:     # a text-only engine (or none) cannot look at the file: say so, never guess
            return dict(NOT_CHECKED)
        try:
            return await bot.check_proof(business=business or "not stated", request=names, explanation=body.explanation,
                                         data=clean.data, mime=clean.mime)
        except Exception as exc:
            log.warning("proof check failed (%s)", type(exc).__name__)
            return dict(NOT_CHECKED)

    (results, summary, priced), proof_result = await asyncio.gather(
        _price(st, country=country, currency=currency, business=business, note=body.explanation, items=body.items, allocation=alloc),
        proof_check())

    status = proof_result["hr_filter_status"]
    priority = route_priority(proof_result["priority_queue"], summary, results)
    ai_result = {"proof": proof_result, "pricing": summary, "pricing_available": priced,
                 "model": bot.model if bot.available else None, "provider": bot.provider, "checked_at": stamp(), "version": 1}

    key = new_object_key()
    wrapped = await st.vault.put_private(key, clean.data)
    try:
        async with st.db.api(session.user_id) as conn:
            new_id = await conn.fetchval(
                _SUBMIT, country, currency, [r.as_dict() for r in results], summary["asked_total_usd_cents"] or 0,
                summary["typical_total_usd_cents"], clean_text(body.explanation, 2000), key, wrapped, clean.mime, clean.sha256,
                status, priority, ai_result)
    except asyncpg.PostgresError:
        await st.vault.erase([f"vault:{key}"])  # do not leave an orphan file behind
        raise
    return NeedsSubmittedOut(id=str(new_id), status="submitted",
                             message="Thank you. Your list and proof are with a SadQah reviewer, who makes the decision. We will show the outcome here.")


@router.get("/needs", response_model=NeedsListOut)
async def my_needs(session: Session = Depends(require_recipient), st: AppState = Depends(state)) -> NeedsListOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_LIST)
    return NeedsListOut(items=[NeedsRequestOut(
        id=str(r["id"]), status=r["status"], country=r["country"], currency=r["local_currency"], items=list(r["items"] or []),
        requested_total_cents=int(r["requested_total_cents"]),
        estimated_total_cents=None if r["estimated_total_cents"] is None else int(r["estimated_total_cents"]),
        has_proof=bool(r["has_proof"]), reviewer_note=r["reviewer_note"], created_at=_iso(r["created_at"])) for r in rows])
