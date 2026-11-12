"""Request and response bodies for the assistant (chat, needs price check, needs submission)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(_Request):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(_Request):
    messages: list[ChatMessage] = Field(min_length=1, max_length=14)
    page: str | None = Field(default=None, max_length=120)


class ChatOut(BaseModel):
    reply: str
    ai: bool                      # False when the built-in FAQ answered because no AI key is configured


class NeedItemIn(_Request):
    name: str = Field(min_length=2, max_length=120)
    quantity: float = Field(gt=0, le=10_000)
    asked_price: float = Field(ge=0, le=1_000_000_000)   # per unit, in the local currency


class NeedsIn(_Request):
    currency: str = Field(pattern=r"^[A-Za-z]{3}$")
    items: list[NeedItemIn] = Field(min_length=1, max_length=20)
    explanation: str = Field(default="", max_length=2000)


class PriceCheckOut(BaseModel):
    ai_available: bool
    country: str
    currency: str
    items: list[dict[str, Any]]
    summary: dict[str, Any]
    disclaimer: str


class NeedsSubmittedOut(BaseModel):
    id: str
    status: str
    message: str


class NeedsRequestOut(BaseModel):
    id: str
    status: str
    country: str
    currency: str | None
    items: list[dict[str, Any]]
    requested_total_cents: int
    estimated_total_cents: int | None
    has_proof: bool
    reviewer_note: str | None
    created_at: str


class NeedsListOut(BaseModel):
    items: list[NeedsRequestOut]
