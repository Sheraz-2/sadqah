"""Public (no login) endpoints plus posting a campaign comment.

    GET  /public/config            GET  /public/stats
    GET  /public/campaigns         GET  /public/campaigns/{slug}
    GET  /public/leaderboard       GET  /public/gratitude
    POST /campaigns/{slug}/comments   (login required)

Everything is read through the `api.public_*` views, which already hide donor identity (anonymous gifts show as
"Anonymous" with the time cut to the day). The only value this module adds to a public gift is a label.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AppState, limit_by_key, rate_limit, require_session, state
from app.core import errors
from app.core.security import Session
from app.core.validation import clean_text
from app.schemas.public import (
    CampaignCardOut,
    CampaignDetailOut,
    CampaignListOut,
    CampaignUpdateOut,
    CommentIn,
    CommentOut,
    CommentPostedOut,
    GratitudeItemOut,
    GratitudeWallOut,
    LeaderboardOut,
    LeaderboardRowOut,
    PublicConfigOut,
    PublicStatsOut,
    RecentGiftOut,
    RecipientOut,
)
from app.services.moderation import screen_text

router = APIRouter(prefix="", tags=["public"])

_PUBLIC_LIMIT = rate_limit("public", 180, 60)
_COMMENT_IP_LIMIT = rate_limit("comment", 20, 600)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")

_STATS = "SELECT recipients_supported, countries_reached, gifts_given, total_given_cents FROM api.public_impact_stats"

# Search text and country are optional ($1 and $2 NULL = no filter). $1 is an already escaped ILIKE pattern.
_LIST_NEWEST = (
    "SELECT slug, title, story, cover_object_key, goal_cents, raised_cents, status, recipient_slug, recipient_name, "
    "business_type, region_country, region_admin1, donor_count, created_at FROM api.public_campaigns "
    "WHERE ($1::text IS NULL OR title ILIKE $1 ESCAPE '\\' OR recipient_name ILIKE $1 ESCAPE '\\' OR story ILIKE $1 ESCAPE '\\') "
    "AND ($2::text IS NULL OR region_country = $2::char(2)) "
    "ORDER BY created_at DESC, slug LIMIT $3 OFFSET $4"
)
_LIST_ALMOST_FUNDED = (
    "SELECT slug, title, story, cover_object_key, goal_cents, raised_cents, status, recipient_slug, recipient_name, "
    "business_type, region_country, region_admin1, donor_count, created_at FROM api.public_campaigns "
    "WHERE ($1::text IS NULL OR title ILIKE $1 ESCAPE '\\' OR recipient_name ILIKE $1 ESCAPE '\\' OR story ILIKE $1 ESCAPE '\\') "
    "AND ($2::text IS NULL OR region_country = $2::char(2)) "
    "ORDER BY (status = 'active') DESC, raised_cents::numeric / GREATEST(goal_cents, 1) DESC, created_at DESC, slug LIMIT $3 OFFSET $4"
)
_LIST_MOST_SUPPORTED = (
    "SELECT slug, title, story, cover_object_key, goal_cents, raised_cents, status, recipient_slug, recipient_name, "
    "business_type, region_country, region_admin1, donor_count, created_at FROM api.public_campaigns "
    "WHERE ($1::text IS NULL OR title ILIKE $1 ESCAPE '\\' OR recipient_name ILIKE $1 ESCAPE '\\' OR story ILIKE $1 ESCAPE '\\') "
    "AND ($2::text IS NULL OR region_country = $2::char(2)) "
    "ORDER BY donor_count DESC, created_at DESC, slug LIMIT $3 OFFSET $4"
)
_LIST_COUNT = (
    "SELECT count(*) FROM api.public_campaigns "
    "WHERE ($1::text IS NULL OR title ILIKE $1 ESCAPE '\\' OR recipient_name ILIKE $1 ESCAPE '\\' OR story ILIKE $1 ESCAPE '\\') "
    "AND ($2::text IS NULL OR region_country = $2::char(2))"
)

_ONE = (
    "SELECT slug, title, story, cover_object_key, goal_cents, raised_cents, status, recipient_slug, recipient_name, "
    "business_type, region_country, region_admin1, donor_count, created_at FROM api.public_campaigns WHERE slug = $1"
)
_UPDATES = (
    "SELECT id, body, media_object_keys, created_at FROM api.public_campaign_updates "
    "WHERE campaign_slug = $1 ORDER BY created_at DESC LIMIT 20"
)
_GIFTS = (
    "SELECT amount_cents, is_anonymous, donor_label, given_at FROM api.public_donation_feed "
    "WHERE campaign_slug = $1 ORDER BY given_at DESC LIMIT 10"
)
_COMMENTS = (
    "SELECT id, author_name, body, media_object_key, created_at FROM api.public_campaign_comments "
    "WHERE campaign_slug = $1 ORDER BY created_at DESC LIMIT 50"
)
_LEADERBOARD = (
    "SELECT rank, donor_label, country_code, points, donation_count FROM api.public_leaderboard "
    "ORDER BY rank, donor_label LIMIT $1"
)
_GRATITUDE = (
    "SELECT id, recipient_name, campaign_slug, thanks_to, body, created_at FROM api.public_gratitude_wall "
    "ORDER BY created_at DESC LIMIT $1"
)
_POST_COMMENT = "SELECT api.fn_post_comment($1, $2, NULL, $3)"


# --------------------------------------------------------------------------- helpers
def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def media_url(key: str) -> str:
    return f"/api/v1/media/{key}"


def _excerpt(story: str, limit: int = 160) -> str:
    text = " ".join((story or "").split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:.-")
    return f"{cut}…"


def _like_pattern(q: str | None) -> str | None:
    text = clean_text(q or "", 80)
    if not text:
        return None
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _card(row: Any) -> dict[str, Any]:
    goal, raised = int(row["goal_cents"]), int(row["raised_cents"])
    percent = 100.0 if goal <= 0 else min(100.0, round(raised * 100.0 / goal, 1))
    return {
        "slug": row["slug"],
        "title": row["title"],
        "excerpt": _excerpt(row["story"]),
        "cover_url": media_url(row["cover_object_key"]) if row["cover_object_key"] else None,
        "goal_cents": goal,
        "raised_cents": raised,
        "remaining_cents": max(0, goal - raised),
        "percent_funded": percent,
        "donor_count": int(row["donor_count"]),
        "status": row["status"],
        "recipient": RecipientOut(
            slug=row["recipient_slug"], name=row["recipient_name"], business_type=row["business_type"],
            region_country=row["region_country"], region_admin1=row["region_admin1"],
        ),
        "created_at": iso(row["created_at"]),
    }


# --------------------------------------------------------------------------- config and stats
@router.get("/public/config", response_model=PublicConfigOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def public_config(response: Response, st: AppState = Depends(state)) -> PublicConfigOut:
    s = st.settings
    response.headers["Cache-Control"] = "public, max-age=30"
    return PublicConfigOut(
        paypal_client_id=s.paypal_client_id, paypal_env=s.paypal_env, min_donation_cents=s.min_donation_cents,
        max_donation_cents=s.max_donation_cents, presets_cents=s.presets_cents,
    )


@router.get("/public/stats", response_model=PublicStatsOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def public_stats(response: Response, st: AppState = Depends(state)) -> PublicStatsOut:
    async with st.db.api() as conn:
        row = await conn.fetchrow(_STATS)
    response.headers["Cache-Control"] = "public, max-age=30"
    return PublicStatsOut(
        recipients_supported=int(row["recipients_supported"]), countries_reached=int(row["countries_reached"]),
        gifts_given=int(row["gifts_given"]), total_given_cents=int(row["total_given_cents"]),
    )


# --------------------------------------------------------------------------- campaigns
@router.get("/public/campaigns", response_model=CampaignListOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def list_campaigns(
    q: str | None = Query(default=None, max_length=80),
    country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    sort: Literal["newest", "almost_funded", "most_supported"] = "newest",
    limit: int = Query(default=12, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10_000),
    st: AppState = Depends(state),
) -> CampaignListOut:
    pattern = _like_pattern(q)
    country_code = country.upper() if country else None
    async with st.db.api() as conn:
        # one literal statement per sort order so scripts/check_sql.py can verify each against the schema
        if sort == "almost_funded":
            rows = await conn.fetch(_LIST_ALMOST_FUNDED, pattern, country_code, limit, offset)
        elif sort == "most_supported":
            rows = await conn.fetch(_LIST_MOST_SUPPORTED, pattern, country_code, limit, offset)
        else:
            rows = await conn.fetch(_LIST_NEWEST, pattern, country_code, limit, offset)
        total = await conn.fetchval(_LIST_COUNT, pattern, country_code)
    return CampaignListOut(items=[CampaignCardOut(**_card(r)) for r in rows], total=int(total or 0))


@router.get("/public/campaigns/{slug}", response_model=CampaignDetailOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def campaign_detail(slug: str, st: AppState = Depends(state)) -> CampaignDetailOut:
    if not _SLUG_RE.match(slug):
        raise errors.not_found()
    async with st.db.api() as conn:
        row = await conn.fetchrow(_ONE, slug)
        if row is None:
            raise errors.not_found()
        updates = await conn.fetch(_UPDATES, slug)
        gifts = await conn.fetch(_GIFTS, slug)
        comments = await conn.fetch(_COMMENTS, slug)
    return CampaignDetailOut(
        **_card(row),
        story=row["story"],
        updates=[
            CampaignUpdateOut(id=str(u["id"]), body=u["body"], media_urls=[media_url(k) for k in (u["media_object_keys"] or [])],
                              created_at=iso(u["created_at"]))
            for u in updates
        ],
        recent_gifts=[
            RecentGiftOut(
                label="Anonymous supporter" if g["is_anonymous"] else g["donor_label"],
                amount_cents=int(g["amount_cents"]), is_anonymous=bool(g["is_anonymous"]), given_at=iso(g["given_at"]),
            )
            for g in gifts
        ],
        comments=[
            CommentOut(id=str(c["id"]), author_name=c["author_name"], body=c["body"],
                       media_url=media_url(c["media_object_key"]) if c["media_object_key"] else None,
                       created_at=iso(c["created_at"]))
            for c in comments
        ],
    )


@router.post("/campaigns/{slug}/comments", status_code=201, response_model=CommentPostedOut,
             dependencies=[Depends(_COMMENT_IP_LIMIT)])
async def post_comment(slug: str, body: CommentIn, session: Session = Depends(require_session),
                       st: AppState = Depends(state)) -> CommentPostedOut:
    if not _SLUG_RE.match(slug):
        raise errors.not_found()
    await limit_by_key(st, "comment-user", str(session.user_id), 10, 600)
    text = clean_text(body.body, 1000)
    verdict = screen_text(text, max_len=1000)
    if not verdict.allowed:
        raise errors.ApiError(422, "message_rejected", verdict.reason or "That comment could not be posted.")
    async with st.db.api(session.user_id) as conn:
        new_id = await conn.fetchval(_POST_COMMENT, slug, text, "approved")
    return CommentPostedOut(id=str(new_id), status="approved")


# --------------------------------------------------------------------------- leaderboard and gratitude
@router.get("/public/leaderboard", response_model=LeaderboardOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def leaderboard(limit: int = Query(default=50, ge=1, le=100), st: AppState = Depends(state)) -> LeaderboardOut:
    async with st.db.api() as conn:
        rows = await conn.fetch(_LEADERBOARD, limit)
    return LeaderboardOut(items=[
        LeaderboardRowOut(rank=int(r["rank"]), donor_label=r["donor_label"], country_code=r["country_code"],
                          points=int(r["points"]), donation_count=int(r["donation_count"]))
        for r in rows
    ])


@router.get("/public/gratitude", response_model=GratitudeWallOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def gratitude_wall(limit: int = Query(default=20, ge=1, le=50), st: AppState = Depends(state)) -> GratitudeWallOut:
    async with st.db.api() as conn:
        rows = await conn.fetch(_GRATITUDE, limit)
    return GratitudeWallOut(items=[
        GratitudeItemOut(id=str(r["id"]), recipient_name=r["recipient_name"], campaign_slug=r["campaign_slug"],
                         thanks_to=r["thanks_to"], body=r["body"], created_at=iso(r["created_at"]))
        for r in rows
    ])
