"""Constraint 1: never fire a live PayPal payout per micro-donation.

Donations only ever write a row to `payout_queue`. This module is what the scheduled worker runs:

    1. Ask the database how many approved-recipient payouts are ready (fn_payout_queue_stats).
    2. Fire when enough are waiting (PAYOUT_MIN_ITEMS_TO_FIRE) OR the oldest has waited long enough
       (PAYOUT_MAX_WAIT_SECONDS). Spikes are smoothed: at most PAYOUT_MAX_ITEMS_PER_BATCH items per cycle.
    3. Claim the rows atomically (FOR UPDATE SKIP LOCKED) and store the batch + its idempotency key
       BEFORE calling PayPal. One PayPal call then pays hundreds of grants.
    4. On a transient failure the batch goes to `retry_wait` with a persisted, jittered exponential delay
       (30s, 1m, 2m, ... 1h). The retry reuses the same sender_batch_id, so it cannot double pay.
    5. A crash between steps 3 and 4 is recovered by the database lease (next_attempt_at): the batch simply
       becomes due again.

No database transaction is ever held open across the HTTP call.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.config import Settings
from app.core.crypto import Crypto, CryptoError
from app.core.db import Database
from app.core.validation import cents_to_decimal_string
from app.services.paypal_client import PayPalClient, PayPalError

log = logging.getLogger("sadqah.payouts")


class ItemRejected(Exception):
    """One grant cannot be sent (unreadable or unsupported destination). It is failed alone; the batch goes on."""


@dataclass(frozen=True)
class BatchOutcome:
    batch_id: uuid.UUID
    status: str            # submitted | retry_wait | failed | skipped
    items_sent: int = 0
    items_rejected: int = 0
    detail: str = ""


def should_fire(ready_count: int, oldest_queued_at: datetime | None, *, min_items: int, max_wait_seconds: int,
                now: datetime | None = None) -> bool:
    if ready_count <= 0:
        return False
    if ready_count >= min_items:
        return True
    if oldest_queued_at is None:
        return False
    now = now or datetime.now(UTC)
    return (now - oldest_queued_at).total_seconds() >= max_wait_seconds


def make_sender_batch_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"SQ-{now:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:12]}"


def build_item(row: dict[str, Any], crypto: Crypto, settings: Settings) -> dict[str, Any]:
    try:
        receiver = crypto.decrypt_text(row["receiver_enc"], aad="recipients.paypal_receiver_enc")
    except CryptoError as exc:
        raise ItemRejected("payout destination could not be read") from exc
    rtype = row["receiver_type"]
    if rtype == "PHONE" and not settings.paypal_allows_phone_receivers:
        raise ItemRejected("phone-number payouts are not supported in the PayPal sandbox")
    if rtype not in ("EMAIL", "PHONE", "PAYPAL_ID"):
        raise ItemRejected("unsupported payout destination type")
    return {
        "recipient_type": rtype,
        "receiver": receiver,
        "amount": {"value": cents_to_decimal_string(int(row["amount_cents"])), "currency": str(row["currency"]).strip()},
        "note": "SadQah micro-grant",              # never contains donor information
        "sender_item_id": row["sender_item_id"],     # = donation UUID: the exact reconciliation key
        "recipient_wallet": "PAYPAL",
    }


async def submit_batch(db: Database, paypal: PayPalClient, crypto: Crypto, settings: Settings,
                       batch_id: uuid.UUID) -> BatchOutcome:
    async with db.session("worker") as conn:
        batch = await conn.fetchrow("SELECT * FROM core.fn_get_batch($1)", batch_id)
        rows = [dict(r) for r in await conn.fetch("SELECT * FROM core.fn_get_batch_items($1)", batch_id)]
    if batch is None or batch["status"] not in ("created", "retry_wait"):
        return BatchOutcome(batch_id, "skipped", detail="batch is not waiting for submission")

    items: list[dict[str, Any]] = []
    rejected = 0
    for row in rows:
        try:
            items.append(build_item(row, crypto, settings))
        except ItemRejected as exc:
            rejected += 1
            async with db.session("worker") as conn:
                await conn.fetchval("SELECT core.fn_apply_payout_item_event($1, 'failed', NULL, NULL, $2, NULL)",
                                    row["sender_item_id"], str(exc)[:300])
            log.warning("grant %s failed before submission: %s", row["sender_item_id"], exc)

    if not items:
        async with db.session("worker") as conn:
            status = await conn.fetchval("SELECT core.fn_batch_submission_failed($1, $2, false, $3)", batch_id,
                                         "no payable items in batch", settings.payout_max_attempts)
        return BatchOutcome(batch_id, str(status or "failed"), 0, rejected, "no payable items")

    try:
        response = await paypal.create_payout_batch(batch["sender_batch_id"], items)
    except PayPalError as exc:
        if exc.is_duplicate:
            # PayPal already has this sender_batch_id: an earlier attempt got through before its answer was lost.
            # The webhooks (keyed by sender_batch_id / sender_item_id) will settle it; nothing to resend.
            async with db.session("worker") as conn:
                await conn.fetchval("SELECT core.fn_mark_batch_submitted($1, NULL)", batch_id)
            return BatchOutcome(batch_id, "submitted", len(items), rejected, "already known to PayPal")
        retryable = exc.retryable or exc.status in (401, 403)     # credentials/permissions: fix config, then it resumes
        async with db.session("worker") as conn:
            status = await conn.fetchval("SELECT core.fn_batch_submission_failed($1, $2, $3, $4)", batch_id,
                                         exc.short(), retryable, settings.payout_max_attempts)
        log.error("batch %s submission failed (%s): %s", batch["sender_batch_id"], status, exc.short())
        return BatchOutcome(batch_id, str(status or "failed"), 0, rejected, exc.short())

    paypal_batch_id = ((response.get("batch_header") or {}).get("payout_batch_id")) or None
    async with db.session("worker") as conn:
        await conn.fetchval("SELECT core.fn_mark_batch_submitted($1, $2)", batch_id, paypal_batch_id)
    log.info("batch %s submitted: %d items", batch["sender_batch_id"], len(items))
    return BatchOutcome(batch_id, "submitted", len(items), rejected)


async def run_once(db: Database, paypal: PayPalClient, crypto: Crypto, settings: Settings,
                   now: datetime | None = None) -> list[BatchOutcome]:
    """One worker cycle: maybe create one new batch, then submit it plus any batch that is due for a retry."""
    outcomes: list[BatchOutcome] = []

    async with db.session("worker") as conn:
        await conn.fetchval("SELECT core.fn_expire_stale_donations(interval '2 hours')")
        stats = await conn.fetchrow("SELECT * FROM core.fn_payout_queue_stats()")

    if should_fire(int(stats["ready_count"]), stats["oldest_queued_at"], min_items=settings.payout_min_items_to_fire,
                   max_wait_seconds=settings.payout_max_wait_seconds, now=now):
        async with db.session("worker") as conn:
            new_batch = await conn.fetchval("SELECT core.fn_claim_payout_batch($1, $2)",
                                            settings.payout_max_items_per_batch, make_sender_batch_id(now))
        if new_batch is not None:
            outcomes.append(await submit_batch(db, paypal, crypto, settings, new_batch))

    for _ in range(5):                                   # retries and crash recovery, bounded per cycle
        async with db.session("worker") as conn:
            due = await conn.fetchval("SELECT core.fn_claim_due_batch()")
        if due is None:
            break
        outcomes.append(await submit_batch(db, paypal, crypto, settings, due))
    return outcomes
