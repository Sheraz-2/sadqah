"""Bodies for the anonymous tracking portal. The token only ever travels in a POST body (never a URL)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DeliveryState = Literal[
    "queued_for_next_batch", "being_prepared", "on_its_way", "awaiting_recipient_claim", "delivered", "needs_attention"
]


class TrackLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=120)


class TrackMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1000)


class TrackDonationOut(BaseModel):
    amount_cents: int
    given_at: str  # a date, never a time: anonymous gifts are not timestamped more finely than the day
    status: Literal["captured", "paid_out"]
    delivery_state: DeliveryState
    thread_open: bool


class TrackCampaignOut(BaseModel):
    slug: str
    title: str


class TrackRecipientOut(BaseModel):
    slug: str
    name: str
    region_country: str
    region_admin1: str | None


class TrackUpdateOut(BaseModel):
    id: str
    body: str
    media_urls: list[str]
    visibility: Literal["public", "donors"]
    created_at: str


class TrackMessageOut(BaseModel):
    id: str
    sender: Literal["donor", "recipient"]
    body: str
    status: Literal["approved", "pending", "rejected"]
    created_at: str


class TrackGratitudeOut(BaseModel):
    body: str
    created_at: str


class TrackViewOut(BaseModel):
    donation: TrackDonationOut
    campaign: TrackCampaignOut
    recipient: TrackRecipientOut
    updates: list[TrackUpdateOut]
    messages: list[TrackMessageOut]
    gratitude: TrackGratitudeOut | None


class TrackMessagePostedOut(BaseModel):
    id: str
    status: Literal["approved", "pending"]
