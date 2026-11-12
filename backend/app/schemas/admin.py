"""Bodies for the staff console. Mirrors docs/API_CONTRACT.md. Staff never receive donor identity: it is not in any view they read."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OverviewOut(BaseModel):
    kyc_waiting: int
    batches_open: int
    payouts_needing_attention: int
    messages_pending: int
    gratitude_pending: int
    reconciliation_ok: bool


class FlagOut(BaseModel):
    code: str
    severity: Literal["info", "warning", "critical"]
    detail: str


class KycCaseOut(BaseModel):
    recipient_id: str
    status: str
    income_monthly_usd_cents: int | None
    face_match: float | None
    fraud_risk: float | None
    flags: list[FlagOut]
    recommended_allocation_cents: int | None
    assessed_at: str | None
    created_at: str


class KycQueueOut(BaseModel):
    items: list[KycCaseOut]


class KycIdentityOut(BaseModel):
    full_name: str
    date_of_birth: str
    id_number_masked: str
    address: str
    doc_country: str | None


class KycDocumentAdminOut(BaseModel):
    id: str
    doc_type: str
    mime_type: str
    size_bytes: int
    scan_status: str
    uploaded_at: str


class KycCaseDetailOut(KycCaseOut):
    identity: KycIdentityOut
    documents: list[KycDocumentAdminOut]


class KycDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected", "suspended"]
    verified_monthly_income_cents: int | None = Field(default=None, strict=True, ge=0, le=100_000_000)
    approved_allocation_cents: int | None = Field(default=None, strict=True, ge=0, le=100_000_000)
    reason: str | None = Field(default=None, max_length=500)


class OkOut(BaseModel):
    ok: bool = True


class BatchOut(BaseModel):
    id: str
    sender_batch_id: str
    paypal_payout_batch_id: str | None
    status: str
    item_count: int
    total_cents: int
    attempt_count: int
    next_attempt_at: str | None
    last_error: str | None
    created_at: str
    submitted_at: str | None
    completed_at: str | None


class BatchListOut(BaseModel):
    items: list[BatchOut]


class PayoutItemOut(BaseModel):
    id: str
    donation_id: str
    recipient_id: str
    amount_cents: int
    status: str
    batch_id: str | None
    paypal_transaction_status: str | None
    failure_reason: str | None
    queued_at: str
    settled_at: str | None
    next_attempt_at: str | None = None       # earliest time the worker may claim it (read-only information)
    eligibility: str | None = None           # queued rows only: "ready" | "waiting" | "kyc_blocked"; None for every other status


class PayoutQueueOut(BaseModel):
    items: list[PayoutItemOut]


class LedgerEventOut(BaseModel):
    id: int
    event_type: str
    donation_id: str | None
    payout_queue_id: str | None
    batch_id: str | None
    recipient_id: str | None
    amount_cents: int | None      # None for events that carry no money amount (batch processing / success / denied / failed)
    source: str | None
    external_event_id: str | None
    details: Any
    created_at: str


class LedgerOut(BaseModel):
    """Newest first. `after_id` continues the list after that row (it returns older events)."""
    items: list[LedgerEventOut]


class ReconciliationRowOut(BaseModel):
    campaign_id: str
    raised_cents: int
    paid_out_cents: int
    donations_captured_cents: int
    payout_queued_cents: int
    payout_in_flight_cents: int
    payout_unclaimed_cents: int
    payout_problem_cents: int
    payout_delivered_cents: int
    raised_mismatch: bool
    paid_out_mismatch: bool


class ReconciliationOut(BaseModel):
    ok: bool
    items: list[ReconciliationRowOut]


class MessageQueueItemOut(BaseModel):
    id: str
    donation_id: str
    sender: Literal["donor", "recipient"]
    body: str
    created_at: str


class MessageQueueOut(BaseModel):
    items: list[MessageQueueItemOut]


class GratitudeQueueItemOut(BaseModel):
    id: str
    recipient_id: str
    is_community: bool
    body: str
    created_at: str


class GratitudeQueueOut(BaseModel):
    items: list[GratitudeQueueItemOut]


class ModerationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=300)
