"""POST /webhooks/paypal: PayPal -> us. Server to server only.

Order matters: verify the signature BEFORE anything else, record the event id (replays become no-ops), apply it in one
transaction, then mark the outcome. A verified event is always answered 200 once it is recorded: if applying it failed the
event stays `failed` in webhook_events and the reconciler retries it, so PayPal does not need to redeliver.
No payload content is logged.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.api.deps import AppState, rate_limit, state
from app.core import errors
from app.services.paypal_client import PayPalError
from app.services.webhook_processor import PROCESSED, process_event

router = APIRouter(prefix="", tags=["webhooks"])
log = logging.getLogger("sadqah.webhooks")

_WEBHOOK_LIMIT = rate_limit("webhook", 1200, 60)
_MAX_BODY = 256 * 1024

_RECORD = "SELECT core.fn_record_webhook($1, $2, $3, $4)"
_FINISH = "SELECT core.fn_finish_webhook($1, $2, $3)"


@router.post("/webhooks/paypal", dependencies=[Depends(_WEBHOOK_LIMIT)])
async def paypal_webhook(request: Request, st: AppState = Depends(state)) -> JSONResponse:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > _MAX_BODY:
        raise errors.ApiError(413, "validation_error", "Webhook body too large.")
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise errors.ApiError(413, "validation_error", "Webhook body too large.")
    try:
        event = json.loads(raw)
    except ValueError:
        raise errors.validation("The webhook body is not valid JSON.") from None
    if not isinstance(event, dict) or not event.get("id") or not event.get("event_type"):
        raise errors.validation("The webhook body is not a PayPal event.")

    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        verified = await st.paypal.verify_webhook(headers, event)
    except PayPalError:
        log.warning("webhook signature check could not reach PayPal")
        raise errors.upstream_unavailable("Could not verify the webhook right now.") from None  # PayPal will redeliver
    if not verified:
        log.warning("webhook rejected: signature did not verify")
        raise errors.validation("The webhook signature could not be verified.")

    event_id = str(event["id"])[:100]
    event_type = str(event["event_type"])[:100]
    resource_id = str((event.get("resource") or {}).get("id") or "")[:100]

    async with st.db.session("webhook") as conn:
        is_new = await conn.fetchval(_RECORD, event_id, event_type, resource_id, event)
    if not is_new:
        return JSONResponse({"status": "duplicate"})

    error: str | None = None
    try:
        async with st.db.session("webhook") as conn:
            outcome, _note = await process_event(conn, event)
        status = "processed" if outcome == PROCESSED else "ignored"
    except Exception as exc:  # recorded as failed below; the reconciler retries it
        status, error = "failed", type(exc).__name__
        log.warning("webhook %s (%s) failed to apply: %s", event_id, event_type, error)
    async with st.db.session("webhook") as conn:
        await conn.fetchval(_FINISH, event_id, status, error)
    return JSONResponse({"status": status})
