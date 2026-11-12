"""Reconciler: the safety net behind the PayPal webhooks.

    python -m app.workers.reconciler

Every cycle it
  1. re-applies webhook events that arrived but failed to apply (core.fn_list_retryable_webhooks, "webhook" role), and
  2. asks PayPal about batches that have been `submitted`/`processing` for too long (core.fn_list_stale_batches, "worker"
     role) and applies the answer exactly like the matching webhooks would (webhook_processor.reconcile_polled_batch).
Every transition is validated in the database and ledger events are append-only, so running this twice is harmless.
Logs contain ids and counts only.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.core.config import Settings, get_settings
from app.core.db import Database
from app.services.paypal_client import PayPalClient, PayPalError
from app.services.webhook_processor import PROCESSED, process_event, reconcile_polled_batch
from app.workers.payout_worker import install_signal_handlers, run_loop

log = logging.getLogger("sadqah.reconciler")

RECONCILE_POLL_SECONDS = 60

_RETRYABLE = "SELECT paypal_event_id, event_type, payload FROM core.fn_list_retryable_webhooks($1)"
_FINISH = "SELECT core.fn_finish_webhook($1, $2, $3)"
_STALE = "SELECT id, sender_batch_id, paypal_payout_batch_id, status FROM core.fn_list_stale_batches($1)"


async def retry_failed_webhooks(db: Database, limit: int = 50) -> int:
    """Returns how many events were applied (processed or deliberately ignored)."""
    async with db.session("webhook") as conn:
        rows = await conn.fetch(_RETRYABLE, limit)
    applied = 0
    for row in rows:
        event = row["payload"]
        status: str
        error: str | None = None
        try:
            async with db.session("webhook") as conn:
                outcome, _note = await process_event(conn, event)
            status = "processed" if outcome == PROCESSED else "ignored"
            applied += 1
        except Exception as exc:  # stays `failed`; picked up again until the 24 hour window closes
            status, error = "failed", type(exc).__name__
            log.warning("retry of webhook %s (%s) failed: %s", row["paypal_event_id"], row["event_type"], error)
        async with db.session("webhook") as conn:
            await conn.fetchval(_FINISH, row["paypal_event_id"], status, error)
    return applied


async def poll_stale_batches(db: Database, paypal: PayPalClient, settings: Settings) -> int:
    """Returns the number of state changes applied from PayPal's answers."""
    async with db.session("worker") as conn:
        batches = await conn.fetch(_STALE, timedelta(seconds=settings.reconcile_stale_after_seconds))
    changes = 0
    for batch in batches:
        paypal_id = batch["paypal_payout_batch_id"]
        if not paypal_id:
            log.warning("batch %s is %s but has no PayPal batch id; needs a human check", batch["id"], batch["status"])
            continue
        try:
            data = await paypal.get_payout_batch(paypal_id)
        except PayPalError as exc:
            log.warning("could not read PayPal batch for %s: %s", batch["id"], exc.short())
            continue
        async with db.session("worker") as conn:
            changes += await reconcile_polled_batch(conn, batch["sender_batch_id"], paypal_id, data)
    return changes


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    db = await Database(settings).open(["webhook", "worker"])
    paypal = PayPalClient(settings)
    stop = asyncio.Event()
    install_signal_handlers(stop)

    async def cycle() -> None:
        retried = await retry_failed_webhooks(db)
        polled = await poll_stale_batches(db, paypal, settings)
        if retried or polled:
            log.info("reconciled: %d webhook events re-applied, %d batch changes from polling", retried, polled)

    log.info("reconciler started")
    try:
        await run_loop(cycle, stop, RECONCILE_POLL_SECONDS, "reconciler")
    finally:
        await paypal.aclose()
        await db.close()
        log.info("reconciler stopped")


if __name__ == "__main__":
    asyncio.run(main())
