"""Staff tools for the needs check and campaign reports (reviewer or admin).

    GET  /admin/needs                       open needs requests, highest priority first, with the assistant's advisory result
    GET  /admin/needs/{id}/proof            the proof file (every view is written to the audit log before any byte is read)
    POST /admin/needs/{id}/decision         approve, decline or ask for more information (only a person changes a status)
    GET  /admin/reports                     open campaign reports
    POST /admin/reports/{id}/resolve        dismiss, or mark as actioned (suspend the case through the KYC decision)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Response

from app.api.deps import AppState, limit_by_key, rate_limit, require_staff, state
from app.core import errors
from app.core.crypto import CryptoError
from app.core.security import Session
from app.core.validation import clean_text
from app.schemas.trust import (
    NeedsCaseOut,
    NeedsDecisionIn,
    NeedsQueueOut,
    OkOut,
    ReportCaseOut,
    ReportQueueOut,
    ReportResolveIn,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])
log = logging.getLogger("sadqah.admin_extra")
_STAFF_LIMIT = rate_limit("admin", 300, 600)

_NEEDS_QUEUE = (
    "SELECT id, recipient_id, status, country, local_currency, items, requested_total_cents, estimated_total_cents, explanation, "
    "hr_filter_status, priority_queue, ai_result, has_proof, proof_mime, reviewer_note, created_at, public_name, business_type, "
    "region_admin1, approved_allocation_cents, kyc_status FROM core.v_admin_needs_queue WHERE status IN ('submitted', 'more_info') "
    "ORDER BY CASE priority_queue WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, created_at LIMIT 200")
_PROOF_REF = "SELECT object_key, wrapped_dek, mime_type FROM core.fn_needs_proof_ref($1)"
_AUDIT_PROOF = "SELECT core.fn_audit_needs_proof_view($1, $2)"
_DECIDE = "SELECT core.fn_decide_needs($1, $2, $3, $4)"
_REPORTS = ("SELECT id, reason, details, status, created_at, campaign_slug, campaign_title, campaign_status, recipient_id, "
            "reports_on_campaign FROM core.v_admin_reports WHERE status = 'open' ORDER BY reports_on_campaign DESC, created_at LIMIT 200")
_RESOLVE = "SELECT core.fn_resolve_report($1, $2, $3)"


def _iso(value) -> str:
    return value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else str(value)


@router.get("/needs", response_model=NeedsQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def needs_queue(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> NeedsQueueOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_NEEDS_QUEUE)
    return NeedsQueueOut(items=[NeedsCaseOut(
        id=str(r["id"]), recipient_id=str(r["recipient_id"]), status=r["status"], recipient_name=r["public_name"],
        business_type=r["business_type"], region_admin1=r["region_admin1"], country=r["country"], currency=r["local_currency"],
        items=list(r["items"] or []), requested_total_cents=int(r["requested_total_cents"]),
        estimated_total_cents=None if r["estimated_total_cents"] is None else int(r["estimated_total_cents"]),
        approved_allocation_cents=None if r["approved_allocation_cents"] is None else int(r["approved_allocation_cents"]),
        kyc_status=r["kyc_status"], explanation=r["explanation"], hr_filter_status=r["hr_filter_status"],
        priority_queue=r["priority_queue"], ai_result=dict(r["ai_result"] or {}), has_proof=bool(r["has_proof"]),
        proof_mime=r["proof_mime"], reviewer_note=r["reviewer_note"], created_at=_iso(r["created_at"])) for r in rows])


@router.get("/needs/{need_id}/proof", dependencies=[Depends(_STAFF_LIMIT)])
async def needs_proof(need_id: uuid.UUID, session: Session = Depends(require_staff), st: AppState = Depends(state)) -> Response:
    await limit_by_key(st, "admin-doc-view", str(session.user_id), 200, 3600)
    async with st.db.session("admin", session.user_id) as conn:
        ref = await conn.fetchrow(_PROOF_REF, need_id)
        if ref is None:
            raise errors.not_found("There is no proof file for that request.")
        await conn.fetchval(_AUDIT_PROOF, session.user_id, need_id)  # on record before any byte is read
    try:
        data = await st.vault.get_private(ref["object_key"], ref["wrapped_dek"])
    except (CryptoError, FileNotFoundError, OSError) as exc:
        log.error("a needs proof file could not be read (%s)", type(exc).__name__)
        raise errors.ApiError(502, "document_unreadable", "That file could not be read. Ask the recipient to submit it again.") from exc
    return Response(content=data, media_type=ref["mime_type"], headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.post("/needs/{need_id}/decision", response_model=OkOut, dependencies=[Depends(_STAFF_LIMIT)])
async def needs_decision(need_id: uuid.UUID, body: NeedsDecisionIn, session: Session = Depends(require_staff),
                         st: AppState = Depends(state)) -> OkOut:
    async with st.db.session("admin", session.user_id) as conn:
        await conn.fetchval(_DECIDE, need_id, body.decision, clean_text(body.note, 500), session.user_id)
    return OkOut()


@router.get("/reports", response_model=ReportQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def reports_queue(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> ReportQueueOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_REPORTS)
    return ReportQueueOut(items=[ReportCaseOut(
        id=str(r["id"]), reason=r["reason"], details=r["details"], status=r["status"], campaign_slug=r["campaign_slug"],
        campaign_title=r["campaign_title"], campaign_status=r["campaign_status"], recipient_id=str(r["recipient_id"]),
        reports_on_campaign=int(r["reports_on_campaign"]), created_at=_iso(r["created_at"])) for r in rows])


@router.post("/reports/{report_id}/resolve", response_model=OkOut, dependencies=[Depends(_STAFF_LIMIT)])
async def report_resolve(report_id: uuid.UUID, body: ReportResolveIn, session: Session = Depends(require_staff),
                         st: AppState = Depends(state)) -> OkOut:
    async with st.db.session("admin", session.user_id) as conn:
        await conn.fetchval(_RESOLVE, report_id, body.status, session.user_id)
    return OkOut()
