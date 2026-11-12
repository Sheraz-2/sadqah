"""Bodies for giving: orders, capture, the donor's own gifts, thank-yous and the giving plan (pledge)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Mirror donor_pledges in database/schema.sql and frontend/src/lib/giving.ts
PLEDGE_MIN_CENTS = 100
PLEDGE_MAX_CENTS = 500_000
PLEDGE_MIN_PERCENT = 1.0
PLEDGE_MAX_PERCENT = 5.0

PledgeKind = Literal["percent_of_income", "fixed_amount"]
PledgeFrequency = Literal["one_time", "monthly", "yearly"]


class CreateOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    amount_cents: int = Field(strict=True)
    is_anonymous: bool


class CreateOrderOut(BaseModel):
    donation_id: str
    paypal_order_id: str
    tracking_token: str | None  # only for anonymous gifts, shown to the donor once


class CaptureOut(BaseModel):
    donation_id: str
    status: Literal["captured"] = "captured"
    amount_cents: int
    is_anonymous: bool
    points_awarded: int | None


class MyDonationOut(BaseModel):
    id: str
    campaign_slug: str
    campaign_title: str
    amount_cents: int
    status: str
    created_at: str
    paid_out_at: str | None
    thread_open: bool


class MyDonationsOut(BaseModel):
    items: list[MyDonationOut]


class MyGratitudeOut(BaseModel):
    id: str
    donation_id: str
    recipient_name: str
    body: str
    created_at: str


class MyGratitudeListOut(BaseModel):
    items: list[MyGratitudeOut]


class PledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: PledgeKind
    percent: float | None = None
    amount_cents: int = Field(strict=True, ge=PLEDGE_MIN_CENTS, le=PLEDGE_MAX_CENTS)
    frequency: PledgeFrequency
    default_anonymous: bool = False

    @model_validator(mode="after")
    def _percent_rules(self) -> PledgeIn:
        if self.kind == "percent_of_income":
            if self.percent is None:
                raise ValueError("percent is required for a percentage plan")
            if not PLEDGE_MIN_PERCENT <= self.percent <= PLEDGE_MAX_PERCENT or (self.percent * 2) % 1 != 0:
                raise ValueError("percent must be between 1 and 5, in steps of 0.5")
        elif self.percent is not None:
            raise ValueError("percent must be empty for a fixed amount")
        return self


class PledgeOut(BaseModel):
    kind: PledgeKind
    percent: float | None
    amount_cents: int
    frequency: PledgeFrequency
    default_anonymous: bool
