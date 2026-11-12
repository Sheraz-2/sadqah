"""Request/response models for the signed-in donor's private message threads (public gifts only)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MessageStatus = Literal["approved", "pending", "rejected"]


class DonorThreadOut(BaseModel):
    donation_id: str
    campaign_slug: str
    campaign_title: str
    recipient_name: str
    donation_status: Literal["captured", "paid_out"]
    thread_open: bool
    paid_out_at: str | None
    last_message_at: str | None
    unread_count: int


class DonorThreadListOut(BaseModel):
    items: list[DonorThreadOut]


class DonorMessageOut(BaseModel):
    id: str
    sender: Literal["donor", "recipient"]
    body: str
    status: MessageStatus
    created_at: str


class DonorThreadViewOut(BaseModel):
    thread: DonorThreadOut
    messages: list[DonorMessageOut]


class DonorMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1000)


class DonorMessagePostedOut(BaseModel):
    id: str
    status: Literal["approved", "pending"]
