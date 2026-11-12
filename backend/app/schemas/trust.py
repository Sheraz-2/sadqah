"""Bodies for the trust features: public statistics, campaign reports, and the staff queues for needs requests and reports."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TrustStatsOut(BaseModel):
    gifts_received: int
    gifts_delivered: int
    raised_cents: int
    delivered_cents: int
    awaiting_payout_cents: int
    platform_fees_cents: int
    refunds: int
    median_payout_seconds: int | None


Reason = Literal["fake_or_misleading", "not_in_need", "impersonation", "inappropriate", "other"]


class ReportIn(_Request):
    reason: Reason
    details: str = Field(default="", max_length=1000)


class ReportReceivedOut(BaseModel):
    received: bool = True
    message: str


# ---- staff
class NeedsCaseOut(BaseModel):
    id: str
    recipient_id: str
    status: str
    recipient_name: str
    business_type: str | None
    region_admin1: str | None
    country: str
    currency: str | None
    items: list[dict[str, Any]]
    requested_total_cents: int
    estimated_total_cents: int | None
    approved_allocation_cents: int | None
    kyc_status: str | None
    explanation: str
    hr_filter_status: str | None
    priority_queue: str | None
    ai_result: dict[str, Any]
    has_proof: bool
    proof_mime: str | None
    reviewer_note: str | None
    created_at: str


class NeedsQueueOut(BaseModel):
    items: list[NeedsCaseOut]


class NeedsDecisionIn(_Request):
    decision: Literal["approved", "declined", "more_info"]
    note: str = Field(default="", max_length=500)


class ReportCaseOut(BaseModel):
    id: str
    reason: str
    details: str
    status: str
    campaign_slug: str
    campaign_title: str
    campaign_status: str
    recipient_id: str
    reports_on_campaign: int
    created_at: str


class ReportQueueOut(BaseModel):
    items: list[ReportCaseOut]


class ReportResolveIn(_Request):
    status: Literal["dismissed", "actioned"]


class OkOut(BaseModel):
    ok: bool = True
