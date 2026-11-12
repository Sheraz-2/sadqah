"""Response and request bodies for the public (no login) endpoints. Mirrors docs/API_CONTRACT.md."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublicConfigOut(BaseModel):
    paypal_client_id: str
    paypal_env: Literal["sandbox", "live"]
    currency: Literal["USD"] = "USD"
    min_donation_cents: int
    max_donation_cents: int
    presets_cents: list[int]


class PublicStatsOut(BaseModel):
    recipients_supported: int
    countries_reached: int
    gifts_given: int
    total_given_cents: int


class RecipientOut(BaseModel):
    slug: str
    name: str
    business_type: str | None
    region_country: str
    region_admin1: str | None


class CampaignCardOut(BaseModel):
    slug: str
    title: str
    excerpt: str
    cover_url: str | None
    goal_cents: int
    raised_cents: int
    remaining_cents: int
    percent_funded: float
    donor_count: int
    status: Literal["active", "funded"]
    recipient: RecipientOut
    created_at: str


class CampaignListOut(BaseModel):
    items: list[CampaignCardOut]
    total: int


class CampaignUpdateOut(BaseModel):
    id: str
    body: str
    media_urls: list[str]
    created_at: str


class RecentGiftOut(BaseModel):
    label: str
    amount_cents: int
    is_anonymous: bool
    given_at: str


class CommentOut(BaseModel):
    id: str
    author_name: str
    body: str
    media_url: str | None
    created_at: str


class CampaignDetailOut(CampaignCardOut):
    story: str
    updates: list[CampaignUpdateOut]
    recent_gifts: list[RecentGiftOut]
    comments: list[CommentOut]


class LeaderboardRowOut(BaseModel):
    rank: int
    donor_label: str
    country_code: str | None
    points: int
    donation_count: int


class LeaderboardOut(BaseModel):
    items: list[LeaderboardRowOut]


class GratitudeItemOut(BaseModel):
    id: str
    recipient_name: str
    campaign_slug: str
    thanks_to: str
    body: str
    created_at: str


class GratitudeWallOut(BaseModel):
    items: list[GratitudeItemOut]


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=1000)


class CommentPostedOut(BaseModel):
    id: str
    status: Literal["approved", "pending"]
