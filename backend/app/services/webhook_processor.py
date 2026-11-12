"""Constraint 3: PayPal events reconcile the ledger by themselves.

Every webhook is (1) verified, (2) recorded once by its PayPal event id (replays become no-ops), and
(3) applied here. Applying an event only calls SQL functions that enforce legal state transitions, so
out-of-order and duplicate events are harmless. The same code path is used by the periodic sweep that
retries events whose first attempt failed.

The rows these functions touch are tied together by identifiers we created BEFORE PayPal was involved:
  donation UUID  ->  PayPal order `custom_id`  ->  capture  ->  payout item `sender_item_id`
and the batch's `sender_batch_id`. Nothing is ever matched by amount, date or name.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

import asyncpg

from app.core.crypto import Crypto
from app.services.paypal_client import amount_to_cents

log = logging.getLogger("sadqah.webhooks")

PROCESSED, IGNORED = "processed", "ignored"

# PAYMENT.PAYOUTS-ITEM.<SUFFIX> -> payout_queue.status
ITEM_EVENT_STATUS = {
    "SUCCEEDED": "succeeded", "UNCLAIMED": "unclaimed", "RETURNED": "returned", "FAILED": "failed",
    "BLOCKED": "blocked", "HELD": "held", "DENIED": "failed", "CANCELED": "failed", "REFUNDED": "returned",
}
# transaction_status values returned by GET /v1/payments/payouts/{id}; PENDING means "no news yet"
TRANSACTION_STATUS = {
    "SUCCESS": "succeeded", "UNCLAIMED": "unclaimed", "RETURNED": "returned", "FAILED": "failed",
    "BLOCKED": "blocked", "ONHOLD": "held", "DENIED": "failed", "CANCELED": "failed", "REFUNDED": "returned",
    "REVERSED": "returned",
}
BATCH_EVENT_STATUS = {"PROCESSING": "processing", "SUCCESS": "success", "DENIED": "denied"}
BATCH_HEADER_STATUS = {"PROCESSING": "processing", "SUCCESS": "success", "DENIED": "denied", "CANCELED": "denied"}


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _capture_id_from_refund(resource: dict[str, Any]) -> str | None:
    related = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("capture_id")
    if related:
        return str(related)
    for link in resource.get("links") or []:
        if link.get("rel") == "up" and "/captures/" in str(link.get("href", "")):
            return str(link["href"]).rstrip("/").rsplit("/", 1)[-1]
    return None


async def record_capture(conn: asyncpg.Connection, donation_id: uuid.UUID, capture_id: str, cents: int,
                         crypto: Crypto | None = None, payer_ref: str | None = None) -> bool:
    """Marks the donation captured. TRUE only the first time; the database refuses a different amount."""
    enc = crypto.encrypt_text(payer_ref, aad="donation_payer_private.payer_ref_enc") if (crypto and payer_ref) else None
    return bool(await conn.fetchval("SELECT core.fn_mark_donation_captured($1, $2, $3, $4)",
                                    donation_id, capture_id, cents, enc))


async def apply_item_status(conn: asyncpg.Connection, sender_item_id: str, status: str, paypal_item_id: str | None,
                            txn_status: str | None, reason: str | None, event_id: str) -> bool:
    return bool(await conn.fetchval(
        "SELECT core.fn_apply_payout_item_event($1, $2::core.payout_item_status, $3, $4, $5, $6)",
        sender_item_id, status, paypal_item_id, txn_status, reason, event_id))


async def apply_batch_status(conn: asyncpg.Connection, sender_batch_id: str | None, paypal_batch_id: str | None,
                             status: str, event_id: str) -> bool:
    return bool(await conn.fetchval("SELECT core.fn_apply_batch_event($1, $2, $3::core.batch_status, $4)",
                                    sender_batch_id, paypal_batch_id, status, event_id))


async def process_event(conn: asyncpg.Connection, event: dict[str, Any]) -> tuple[str, str]:
    """Applies one PayPal event. Returns (PROCESSED | IGNORED, note). Raises on anything that needs a retry or a human."""
    etype = str(event.get("event_type", ""))
    event_id = str(event.get("id", ""))
    resource = event.get("resource") or {}

    # ---- money in -------------------------------------------------------------------------------------------
    if etype == "PAYMENT.CAPTURE.COMPLETED":
        amount = resource.get("amount") or {}
        if amount.get("currency_code") != "USD":
            return IGNORED, "non-USD capture"
        donation_id = _uuid_or_none(resource.get("custom_id"))
        if donation_id is None:
            order_id = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
            row = await conn.fetchrow("SELECT * FROM core.fn_donation_by_order($1)", order_id) if order_id else None
            donation_id = row["donation_id"] if row else None
        if donation_id is None:
            return IGNORED, "capture does not belong to a SadQah donation"
        changed = await record_capture(conn, donation_id, str(resource["id"]), amount_to_cents(amount["value"]))
        return PROCESSED, "donation captured" if changed else "already captured (replay)"

    if etype in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        capture_id = _capture_id_from_refund(resource)
        if not capture_id:
            return IGNORED, "refund without a capture reference"
        changed = bool(await conn.fetchval("SELECT core.fn_apply_capture_refund($1)", capture_id))
        return (PROCESSED, "donation refunded") if changed else (IGNORED, "no captured donation for this refund")

    if etype in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED", "PAYMENT.CAPTURE.PENDING"):
        return IGNORED, "no state change needed"

    # ---- money out: batch -----------------------------------------------------------------------------------
    if etype.startswith("PAYMENT.PAYOUTSBATCH."):
        status = BATCH_EVENT_STATUS.get(etype.rsplit(".", 1)[-1])
        if status is None:
            return IGNORED, "unhandled batch event"
        header = resource.get("batch_header") or resource
        sender_batch_id = ((header.get("sender_batch_header") or {}).get("sender_batch_id"))
        paypal_batch_id = header.get("payout_batch_id") or resource.get("payout_batch_id")
        changed = await apply_batch_status(conn, sender_batch_id, paypal_batch_id, status, event_id)
        return (PROCESSED, f"batch -> {status}") if changed else (IGNORED, "batch event was stale or unknown")

    # ---- money out: single grant ----------------------------------------------------------------------------
    if etype.startswith("PAYMENT.PAYOUTS-ITEM."):
        status = ITEM_EVENT_STATUS.get(etype.rsplit(".", 1)[-1])
        if status is None:
            return IGNORED, "unhandled item event"
        sender_item_id = (resource.get("payout_item") or {}).get("sender_item_id")
        if not sender_item_id:
            return IGNORED, "item event without sender_item_id"
        errors = resource.get("errors") or {}
        reason = errors.get("message") or errors.get("name")
        changed = await apply_item_status(conn, str(sender_item_id), status, resource.get("payout_item_id"),
                                          resource.get("transaction_status"), reason, event_id)
        return (PROCESSED, f"grant -> {status}") if changed else (IGNORED, "item event was stale or unknown")

    return IGNORED, "event type not used by SadQah"


async def reconcile_polled_batch(conn: asyncpg.Connection, sender_batch_id: str, paypal_batch_id: str,
                                 data: dict[str, Any]) -> int:
    """Applies the result of GET /v1/payments/payouts/{id}. Used when a webhook may have been lost."""
    changes = 0
    for item in data.get("items") or []:
        status = TRANSACTION_STATUS.get(str(item.get("transaction_status", "")).upper())
        sid = (item.get("payout_item") or {}).get("sender_item_id")
        if status and sid:
            errors = item.get("errors") or {}
            if await apply_item_status(conn, str(sid), status, item.get("payout_item_id"), item.get("transaction_status"),
                                       errors.get("message") or errors.get("name"),
                                       f"poll:{paypal_batch_id}:{sid}:{status}"[:120]):
                changes += 1
    header_status = BATCH_HEADER_STATUS.get(str((data.get("batch_header") or {}).get("batch_status", "")).upper())
    if header_status and await apply_batch_status(conn, sender_batch_id, paypal_batch_id, header_status,
                                                  f"poll:{paypal_batch_id}:{header_status}"):
        changes += 1
    return changes
