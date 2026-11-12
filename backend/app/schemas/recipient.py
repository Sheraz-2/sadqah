"""Bodies for the recipient portal. Mirrors docs/API_CONTRACT.md (RecipientMe and friends)."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PayoutType = Literal["EMAIL", "PHONE"]
KycStatus = Literal["not_started", "documents_pending", "processing", "needs_human_review", "approved", "rejected", "suspended"]
KycDocType = Literal["national_id", "passport", "utility_bill", "selfie", "bank_statement", "proof_of_income"]
KycMissing = Literal["identity_details_and_consent", "national_id_or_passport", "utility_bill", "selfie",
                     "bank_statement_or_proof_of_income"]


# ------------------------------------------------------------------ requests
class ProfileCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_name: str = Field(min_length=2, max_length=60)
    story: str = Field(default="", max_length=4000)
    business_type: str | None = Field(default=None, max_length=80)
    region_country: str = Field(pattern=r"^[A-Za-z]{2}$")
    region_admin1: str | None = Field(default=None, max_length=80)
    payout_type: PayoutType
    payout_handle: str = Field(min_length=3, max_length=254)


class ProfileUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_name: str | None = Field(default=None, min_length=2, max_length=60)
    story: str | None = Field(default=None, max_length=4000)
    business_type: str | None = Field(default=None, max_length=80)
    region_admin1: str | None = Field(default=None, max_length=80)


class PayoutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payout_type: PayoutType
    payout_handle: str = Field(min_length=3, max_length=254)


class PublicIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public: bool


class CampaignCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=120)
    story: str = Field(default="", max_length=4000)
    goal_cents: int = Field(strict=True, ge=100, le=100_000_000)


class MessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1000)


class GratitudeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    donation_id: uuid.UUID
    body: str = Field(min_length=1, max_length=1000)


# ------------------------------------------------------------------ responses
class ProfileOut(BaseModel):
    slug: str
    public_name: str
    story: str
    business_type: str | None
    region_country: str
    region_admin1: str | None
    profile_public: bool


class KycDocumentOut(BaseModel):
    doc_type: KycDocType
    uploaded_at: str
    scan_status: Literal["pending", "clean", "infected", "failed"]


class KycStateOut(BaseModel):
    status: KycStatus
    rejection_reason: str | None
    approved_allocation_cents: int | None
    identity_saved: bool
    documents: list[KycDocumentOut]
    missing: list[KycMissing]


class PayoutOut(BaseModel):
    type: PayoutType
    handle_masked: str


class MyCampaignOut(BaseModel):
    slug: str
    title: str
    goal_cents: int
    raised_cents: int
    paid_out_cents: int
    status: Literal["draft", "active", "funded", "closed"]


class BalanceOut(BaseModel):
    raised_cents: int
    queued_cents: int
    in_flight_cents: int
    unclaimed_cents: int
    delivered_cents: int
    problem_cents: int


class RecipientMeOut(BaseModel):
    profile: ProfileOut | None
    kyc: KycStateOut | None
    payout: PayoutOut | None
    campaign: MyCampaignOut | None
    balance: BalanceOut | None


class UpdatePostedOut(BaseModel):
    id: str


class RecipientDonationOut(BaseModel):
    donation_id: str
    campaign_slug: str
    donor_label: str
    is_anonymous: bool
    amount_cents: int
    delivery_state: str
    captured_at: str
    paid_out_at: str | None
    has_gratitude: bool


class RecipientDonationsOut(BaseModel):
    items: list[RecipientDonationOut]


class ThreadOut(BaseModel):
    thread_id: str
    donor_label: str
    amount_cents: int
    paid_out_at: str | None
    last_message_at: str | None
    unread_count: int


class ThreadListOut(BaseModel):
    items: list[ThreadOut]


class KindWordOut(BaseModel):
    """A public, approved comment on one of the recipient's own campaigns. No author id; the name is the public display name."""
    id: str
    campaign_slug: str
    author_name: str
    body: str
    created_at: str


class KindWordsOut(BaseModel):
    items: list[KindWordOut]


class ThreadMessageOut(BaseModel):
    id: str
    sender: Literal["donor", "recipient"]
    body: str
    status: Literal["approved", "pending", "rejected"]
    created_at: str


class ThreadViewOut(BaseModel):
    messages: list[ThreadMessageOut]


class MessagePostedOut(BaseModel):
    id: str
    status: Literal["approved", "pending"]


class GratitudePostedOut(BaseModel):
    id: str
    audience: Literal["donor", "community"]
    status: Literal["approved", "pending"]
