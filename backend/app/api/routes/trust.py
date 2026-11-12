"""Public trust features.

    GET  /public/trust-stats        counts and sums that show what has actually happened to gifts (no one is identifiable)
    POST /campaigns/{slug}/report   report a campaign as misleading, not in need, impersonation, inappropriate or other
"""
from __future__ import annotations

import re

import asyncpg
from fastapi import APIRouter, Depends

from app.api.deps import AppState, optional_session, rate_limit, state
from app.core import errors
from app.core.security import Session
from app.core.validation import clean_text
from app.schemas.trust import ReportIn, ReportReceivedOut, TrustStatsOut

router = APIRouter(tags=["trust"])

_PUBLIC_LIMIT = rate_limit("public", 180, 60)
_REPORT_LIMIT = rate_limit("report", 10, 3600)
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")

_STATS = ("SELECT gifts_received, gifts_delivered, raised_cents, delivered_cents, awaiting_payout_cents, platform_fees_cents, "
          "refunds, median_payout_seconds FROM api.public_trust_stats")
_REPORT = "SELECT api.fn_report_campaign($1, $2, $3)"


@router.get("/public/trust-stats", response_model=TrustStatsOut, dependencies=[Depends(_PUBLIC_LIMIT)])
async def trust_stats(st: AppState = Depends(state)) -> TrustStatsOut:
    async with st.db.api() as conn:
        r = await conn.fetchrow(_STATS)
    return TrustStatsOut(
        gifts_received=int(r["gifts_received"]), gifts_delivered=int(r["gifts_delivered"]), raised_cents=int(r["raised_cents"]),
        delivered_cents=int(r["delivered_cents"]), awaiting_payout_cents=int(r["awaiting_payout_cents"]),
        platform_fees_cents=int(r["platform_fees_cents"]), refunds=int(r["refunds"]),
        median_payout_seconds=None if r["median_payout_seconds"] is None else int(r["median_payout_seconds"]))


@router.post("/campaigns/{slug}/report", status_code=201, response_model=ReportReceivedOut, dependencies=[Depends(_REPORT_LIMIT)])
async def report_campaign(slug: str, body: ReportIn, session: Session | None = Depends(optional_session),
                          st: AppState = Depends(state)) -> ReportReceivedOut:
    if not _SLUG_RE.match(slug):
        raise errors.not_found("We could not find that campaign.")
    details = clean_text(body.details, 1000)
    if body.reason == "other" and len(details) < 10:
        raise errors.validation("Please tell us a little more.", {"details": "Describe your concern in a sentence or two."})
    try:
        async with st.db.api(session.user_id if session else None) as conn:
            await conn.fetchval(_REPORT, slug, body.reason, details)
    except asyncpg.UniqueViolationError:
        raise errors.conflict("You have already reported this campaign. A reviewer will look at it.") from None
    return ReportReceivedOut(message="Thank you. A SadQah reviewer will look at this campaign. We do not tell the recipient who reported it.")
