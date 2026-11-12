"""Staff console API. Roles: reviewer and admin (payout requeue: admin only).

Everything here runs on the `admin` database role, which can read the masked admin views and execute audited decision
functions, nothing else. Donor identity is not in any of those views.

    GET  /admin/overview                         GET  /admin/kyc/queue          GET /admin/kyc/{recipient_id}
    GET  /admin/kyc/documents/{id}/content       POST /admin/kyc/{recipient_id}/decision
    GET  /admin/payouts/batches                  GET  /admin/payouts/queue      POST /admin/payouts/{id}/requeue
    GET  /admin/ledger                           GET  /admin/reconciliation
    GET  /admin/moderation/messages|gratitude    POST /admin/moderation/messages|gratitude/{id}
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import AppState, limit_by_key, rate_limit, require_admin, require_staff, state
from app.api.routes.public import iso
from app.core import aad, errors
from app.core.crypto import CryptoError
from app.core.security import Session
from app.core.validation import clean_text, mask_nic
from app.schemas.admin import (
    BatchListOut,
    BatchOut,
    FlagOut,
    GratitudeQueueItemOut,
    GratitudeQueueOut,
    KycCaseDetailOut,
    KycCaseOut,
    KycDecisionIn,
    KycDocumentAdminOut,
    KycIdentityOut,
    KycQueueOut,
    LedgerEventOut,
    LedgerOut,
    MessageQueueItemOut,
    MessageQueueOut,
    ModerationIn,
    OkOut,
    OverviewOut,
    PayoutItemOut,
    PayoutQueueOut,
    ReconciliationOut,
    ReconciliationRowOut,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_staff)])
log = logging.getLogger("sadqah.admin")

_STAFF_LIMIT = rate_limit("admin", 300, 600)
PAYOUT_STATUSES = ("queued", "batched", "submitted", "succeeded", "unclaimed", "returned", "failed", "blocked", "held", "cancelled")

_OVERVIEW = (
    "SELECT (SELECT count(*) FROM core.v_admin_kyc_queue WHERE status = 'needs_human_review') AS kyc_waiting, "
    "(SELECT count(*) FROM core.v_admin_batches WHERE status IN ('created', 'retry_wait', 'submitted', 'processing')) AS batches_open, "
    "(SELECT count(*) FROM core.v_admin_payout_queue WHERE status IN ('failed', 'blocked', 'returned')) AS payouts_needing_attention, "
    "(SELECT count(*) FROM core.v_admin_message_queue) AS messages_pending, "
    "(SELECT count(*) FROM core.v_admin_gratitude_queue) AS gratitude_pending, "
    "(SELECT count(*) FROM core.v_admin_reconciliation WHERE raised_mismatch OR paid_out_mismatch) AS reconciliation_bad"
)
_KYC_QUEUE = (
    "SELECT recipient_id, status, ai_extracted_monthly_income_cents, ai_face_match_score, ai_fraud_risk_score, ai_fraud_flags, "
    "ai_recommended_allocation_cents, ai_assessed_at, created_at FROM core.v_admin_kyc_queue ORDER BY created_at LIMIT 200"
)
_KYC_CASE = (
    "SELECT recipient_id, status, full_name_enc, dob_enc, nic_number_enc, address_enc, doc_country, "
    "ai_extracted_monthly_income_cents, ai_face_match_score, ai_fraud_risk_score, ai_fraud_flags, "
    "ai_recommended_allocation_cents, ai_assessed_at, created_at FROM core.recipients_kyc WHERE recipient_id = $1"
)
_KYC_DOCS = ("SELECT id, doc_type, mime_type, size_bytes, scan_status, uploaded_at FROM core.kyc_documents "
             "WHERE recipient_id = $1 AND deleted_at IS NULL ORDER BY uploaded_at")
_KYC_DOC = "SELECT object_key, wrapped_dek, mime_type FROM core.kyc_documents WHERE id = $1 AND deleted_at IS NULL"
_AUDIT_DOC_VIEW = "SELECT core.fn_audit_kyc_document_view($1, $2)"
_REVIEW_KYC = "SELECT core.fn_review_kyc($1, $2, $3, $4, $5, $6)"
_BATCHES = ("SELECT id, sender_batch_id, paypal_payout_batch_id, status, item_count, total_cents, attempt_count, next_attempt_at, "
            "last_error, created_at, submitted_at, completed_at FROM core.v_admin_batches ORDER BY created_at DESC LIMIT $1")
# Read-only. next_attempt_at comes from the existing view; kyc_approved repeats the worker's own claim condition
# (core.fn_claim_payout_batch / fn_payout_queue_stats: recipient KYC is 'approved') and db_now keeps the comparison on the database clock.
_QUEUE_ALL = (
    "SELECT q.id, q.donation_id, q.recipient_id, q.amount_cents, q.status, q.batch_id, q.paypal_transaction_status, "
    "q.failure_reason, q.queued_at, q.settled_at, q.next_attempt_at, now() AS db_now, "
    "EXISTS (SELECT 1 FROM core.recipients_kyc k WHERE k.recipient_id = q.recipient_id AND k.status = 'approved') AS kyc_approved "
    "FROM core.v_admin_payout_queue q ORDER BY q.queued_at DESC LIMIT $1")
_QUEUE_BY_STATUS = (
    "SELECT q.id, q.donation_id, q.recipient_id, q.amount_cents, q.status, q.batch_id, q.paypal_transaction_status, "
    "q.failure_reason, q.queued_at, q.settled_at, q.next_attempt_at, now() AS db_now, "
    "EXISTS (SELECT 1 FROM core.recipients_kyc k WHERE k.recipient_id = q.recipient_id AND k.status = 'approved') AS kyc_approved "
    "FROM core.v_admin_payout_queue q WHERE q.status = $2 ORDER BY q.queued_at DESC LIMIT $1")
_REQUEUE = "SELECT core.fn_requeue_payout($1, $2)"
_LEDGER_FIRST = ("SELECT id, event_type, donation_id, payout_queue_id, batch_id, recipient_id, amount_cents, source, "
                 "external_event_id, details, created_at FROM core.v_admin_ledger ORDER BY id DESC LIMIT $1")
_LEDGER_AFTER = ("SELECT id, event_type, donation_id, payout_queue_id, batch_id, recipient_id, amount_cents, source, "
                 "external_event_id, details, created_at FROM core.v_admin_ledger WHERE id < $2 ORDER BY id DESC LIMIT $1")
_RECONCILIATION = (
    "SELECT campaign_id, raised_cents, paid_out_cents, donations_captured_cents, payout_queued_cents, payout_in_flight_cents, "
    "payout_unclaimed_cents, payout_problem_cents, payout_delivered_cents, raised_mismatch, paid_out_mismatch "
    "FROM core.v_admin_reconciliation ORDER BY (raised_mismatch OR paid_out_mismatch) DESC, campaign_id"
)
_MESSAGE_QUEUE = ("SELECT id, donation_id, sender, body_enc, created_at FROM core.v_admin_message_queue "
                  "ORDER BY created_at LIMIT 100")
_MODERATE_MESSAGE = "SELECT core.fn_moderate_message($1, $2, $3, $4)"
_GRATITUDE_QUEUE = ("SELECT id, recipient_id, is_community, body, created_at FROM core.v_admin_gratitude_queue "
                    "ORDER BY created_at LIMIT 100")
_MODERATE_GRATITUDE = "SELECT core.fn_moderate_gratitude($1, $2, $3)"


def _opt_iso(value: Any) -> str | None:
    return iso(value) if value is not None else None


def _opt_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _opt_float(value: Decimal | float | None) -> float | None:
    return float(value) if value is not None else None


def _opt_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _flags(raw: Any) -> list[FlagOut]:
    out: list[FlagOut] = []
    for f in raw or []:
        severity = f.get("severity") if isinstance(f, dict) else None
        out.append(FlagOut(code=str(f.get("code", "unknown")), severity=severity if severity in ("info", "warning", "critical") else "info",
                           detail=str(f.get("detail", ""))[:300]))
    return out


def _case(r: Any) -> KycCaseOut:
    return KycCaseOut(
        recipient_id=str(r["recipient_id"]), status=r["status"],
        income_monthly_usd_cents=_opt_int(r["ai_extracted_monthly_income_cents"]), face_match=_opt_float(r["ai_face_match_score"]),
        fraud_risk=_opt_float(r["ai_fraud_risk_score"]), flags=_flags(r["ai_fraud_flags"]),
        recommended_allocation_cents=_opt_int(r["ai_recommended_allocation_cents"]), assessed_at=_opt_iso(r["ai_assessed_at"]),
        created_at=iso(r["created_at"]))


# --------------------------------------------------------------------------- overview
@router.get("/overview", response_model=OverviewOut, dependencies=[Depends(_STAFF_LIMIT)])
async def overview(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> OverviewOut:
    async with st.db.session("admin", session.user_id) as conn:
        r = await conn.fetchrow(_OVERVIEW)
    return OverviewOut(kyc_waiting=int(r["kyc_waiting"]), batches_open=int(r["batches_open"]),
                       payouts_needing_attention=int(r["payouts_needing_attention"]), messages_pending=int(r["messages_pending"]),
                       gratitude_pending=int(r["gratitude_pending"]), reconciliation_ok=int(r["reconciliation_bad"]) == 0)


# --------------------------------------------------------------------------- KYC
@router.get("/kyc/queue", response_model=KycQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def kyc_queue(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> KycQueueOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_KYC_QUEUE)
    return KycQueueOut(items=[_case(r) for r in rows])


@router.get("/kyc/documents/{doc_id}/content", dependencies=[Depends(_STAFF_LIMIT)])
async def kyc_document_content(doc_id: uuid.UUID, session: Session = Depends(require_staff),
                               st: AppState = Depends(state)) -> Response:
    await limit_by_key(st, "admin-doc-view", str(session.user_id), 200, 3600)
    async with st.db.session("admin", session.user_id) as conn:
        doc = await conn.fetchrow(_KYC_DOC, doc_id)
        if doc is None:
            raise errors.not_found("We could not find that document.")
        await conn.fetchval(_AUDIT_DOC_VIEW, session.user_id, doc_id)  # the view is on record before any byte is read
    try:
        data = await st.vault.get_private(doc["object_key"], doc["wrapped_dek"])
    except (CryptoError, FileNotFoundError, OSError) as exc:
        log.error("a KYC document could not be read (%s)", type(exc).__name__)
        raise errors.ApiError(502, "document_unreadable", "That document could not be read. Ask the applicant to upload it again.") from exc
    return Response(content=data, media_type=doc["mime_type"], headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Disposition": "inline",
        "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.get("/kyc/{recipient_id}", response_model=KycCaseDetailOut, dependencies=[Depends(_STAFF_LIMIT)])
async def kyc_case(recipient_id: uuid.UUID, session: Session = Depends(require_staff),
                   st: AppState = Depends(state)) -> KycCaseDetailOut:
    async with st.db.session("admin", session.user_id) as conn:
        r = await conn.fetchrow(_KYC_CASE, recipient_id)
        if r is None:
            raise errors.not_found("We could not find that application.")
        docs = await conn.fetch(_KYC_DOCS, recipient_id)

    def read(blob: bytes | None, label: str) -> str:
        if blob is None:
            return ""
        try:
            return st.crypto.decrypt_text(blob, label)
        except CryptoError:
            log.error("a KYC field could not be decrypted (%s)", label)
            return "(unreadable)"

    nic = read(r["nic_number_enc"], aad.KYC_NIC)
    case = _case(r)
    return KycCaseDetailOut(
        **case.model_dump(),
        identity=KycIdentityOut(full_name=read(r["full_name_enc"], aad.KYC_FULL_NAME), date_of_birth=read(r["dob_enc"], aad.KYC_DOB),
                                id_number_masked=mask_nic(nic) if nic else "", address=read(r["address_enc"], aad.KYC_ADDRESS),
                                doc_country=(r["doc_country"] or None)),
        documents=[KycDocumentAdminOut(id=str(d["id"]), doc_type=d["doc_type"], mime_type=d["mime_type"], size_bytes=int(d["size_bytes"]),
                                       scan_status=d["scan_status"], uploaded_at=iso(d["uploaded_at"])) for d in docs])


@router.post("/kyc/{recipient_id}/decision", response_model=OkOut, dependencies=[Depends(_STAFF_LIMIT)])
async def kyc_decision(recipient_id: uuid.UUID, body: KycDecisionIn, session: Session = Depends(require_staff),
                       st: AppState = Depends(state)) -> OkOut:
    s = st.settings
    reason = clean_text(body.reason or "", 500)
    if body.decision == "approved":
        if body.verified_monthly_income_cents is None:
            raise errors.validation("Enter the monthly income you verified from the documents.",
                                    {"verified_monthly_income_cents": "Required to approve."})
        if body.verified_monthly_income_cents >= s.kyc_distress_threshold_cents:
            raise errors.validation("Verified income must be below the program threshold.",
                                    {"verified_monthly_income_cents": "At or above the distress threshold."})
        allocation = body.approved_allocation_cents
        if allocation is not None and not s.kyc_allocation_min_cents <= allocation <= s.kyc_allocation_max_cents:
            raise errors.validation("That allocation is outside the allowed range.", {
                "approved_allocation_cents": f"Must be between {s.kyc_allocation_min_cents} and {s.kyc_allocation_max_cents} cents."})
    elif len(reason) < 10:
        raise errors.validation("Please give the applicant a reason (at least 10 characters).", {"reason": "Required."})
    try:
        async with st.db.session("admin", session.user_id) as conn:  # refuses unreviewable cases (404)
            await conn.fetchval(_REVIEW_KYC, recipient_id, body.decision, body.verified_monthly_income_cents,
                                body.approved_allocation_cents, session.user_id, reason or None)
    except asyncpg.CheckViolationError as exc:
        # The database is the last line of defence: approval needs a finished assessment, identity data and income < threshold.
        raise errors.conflict("This application cannot be approved yet: it needs a completed assessment, saved identity "
                              "details and a verified income below the program threshold.") from exc
    return OkOut()


# --------------------------------------------------------------------------- payouts
@router.get("/payouts/batches", response_model=BatchListOut, dependencies=[Depends(_STAFF_LIMIT)])
async def payout_batches(limit: int = Query(50, ge=1, le=200), session: Session = Depends(require_staff),
                         st: AppState = Depends(state)) -> BatchListOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_BATCHES, limit)
    return BatchListOut(items=[
        BatchOut(id=str(b["id"]), sender_batch_id=b["sender_batch_id"], paypal_payout_batch_id=b["paypal_payout_batch_id"],
                 status=b["status"], item_count=int(b["item_count"]), total_cents=int(b["total_cents"]),
                 attempt_count=int(b["attempt_count"]), next_attempt_at=_opt_iso(b["next_attempt_at"]),
                 last_error=(b["last_error"] or None) and str(b["last_error"])[:300], created_at=iso(b["created_at"]),
                 submitted_at=_opt_iso(b["submitted_at"]), completed_at=_opt_iso(b["completed_at"])) for b in rows])


def payout_eligibility(status: str, next_attempt_at: Any, kyc_approved: bool, db_now: Any) -> str | None:
    """Why a QUEUED payout has not been sent yet. Mirrors the worker's claim filter and changes nothing.
    kyc_blocked: the recipient's KYC is not 'approved' (the worker skips it). waiting: scheduled for later. ready: the worker may
    claim it; it is still sent only when a batch fires (enough ready items, or the oldest has waited long enough). Other statuses: None."""
    if status != "queued":
        return None
    if not kyc_approved:
        return "kyc_blocked"
    if next_attempt_at is not None and db_now is not None and next_attempt_at > db_now:
        return "waiting"
    return "ready"


@router.get("/payouts/queue", response_model=PayoutQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def payout_queue(status: str | None = Query(None), limit: int = Query(200, ge=1, le=500),
                       session: Session = Depends(require_staff), st: AppState = Depends(state)) -> PayoutQueueOut:
    if status is not None and status not in PAYOUT_STATUSES:
        raise errors.validation("Unknown status.", {"status": "Choose one of: " + ", ".join(PAYOUT_STATUSES)})
    async with st.db.session("admin", session.user_id) as conn:
        rows = await (conn.fetch(_QUEUE_ALL, limit) if status is None else conn.fetch(_QUEUE_BY_STATUS, limit, status))
    return PayoutQueueOut(items=[
        PayoutItemOut(id=str(q["id"]), donation_id=str(q["donation_id"]), recipient_id=str(q["recipient_id"]),
                      amount_cents=int(q["amount_cents"]), status=q["status"], batch_id=_opt_str(q["batch_id"]),
                      paypal_transaction_status=q["paypal_transaction_status"],
                      failure_reason=(q["failure_reason"] or None) and str(q["failure_reason"])[:300],
                      queued_at=iso(q["queued_at"]), settled_at=_opt_iso(q["settled_at"]),
                      next_attempt_at=_opt_iso(q["next_attempt_at"]),
                      eligibility=payout_eligibility(q["status"], q["next_attempt_at"], bool(q["kyc_approved"]), q["db_now"]))
        for q in rows])


@router.post("/payouts/{payout_id}/requeue", response_model=OkOut, dependencies=[Depends(require_admin), Depends(_STAFF_LIMIT)])
async def requeue_payout(payout_id: uuid.UUID, session: Session = Depends(require_admin),
                         st: AppState = Depends(state)) -> OkOut:
    async with st.db.session("admin", session.user_id) as conn:
        changed = await conn.fetchval(_REQUEUE, payout_id, session.user_id)
    if not changed:
        raise errors.conflict("Only failed or blocked payouts can be requeued.")
    return OkOut()


# --------------------------------------------------------------------------- ledger and reconciliation
@router.get("/ledger", response_model=LedgerOut, dependencies=[Depends(_STAFF_LIMIT)])
async def ledger(after_id: int | None = Query(None, ge=1), limit: int = Query(200, ge=1, le=500),
                 session: Session = Depends(require_staff), st: AppState = Depends(state)) -> LedgerOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await (conn.fetch(_LEDGER_FIRST, limit) if after_id is None else conn.fetch(_LEDGER_AFTER, limit, after_id))
    return LedgerOut(items=[
        LedgerEventOut(id=int(e["id"]), event_type=e["event_type"], donation_id=_opt_str(e["donation_id"]),
                       payout_queue_id=_opt_str(e["payout_queue_id"]), batch_id=_opt_str(e["batch_id"]),
                       recipient_id=_opt_str(e["recipient_id"]), amount_cents=None if e["amount_cents"] is None else int(e["amount_cents"]), source=e["source"],
                       external_event_id=e["external_event_id"], details=e["details"], created_at=iso(e["created_at"])) for e in rows])


@router.get("/reconciliation", response_model=ReconciliationOut, dependencies=[Depends(_STAFF_LIMIT)])
async def reconciliation(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> ReconciliationOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_RECONCILIATION)
    items = [ReconciliationRowOut(campaign_id=str(r["campaign_id"]), **{
        k: (bool(r[k]) if k.endswith("mismatch") else int(r[k])) for k in ReconciliationRowOut.model_fields if k != "campaign_id"})
        for r in rows]
    return ReconciliationOut(ok=not any(i.raised_mismatch or i.paid_out_mismatch for i in items), items=items)


# --------------------------------------------------------------------------- moderation
@router.get("/moderation/messages", response_model=MessageQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def message_queue(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> MessageQueueOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_MESSAGE_QUEUE)
    items: list[MessageQueueItemOut] = []
    for m in rows:
        try:
            text = st.crypto.decrypt_text(m["body_enc"], aad.message(m["donation_id"]))
        except CryptoError:
            log.error("a queued message could not be decrypted (message %s)", m["id"])
            continue
        items.append(MessageQueueItemOut(id=str(m["id"]), donation_id=str(m["donation_id"]), sender=m["sender"], body=text,
                                         created_at=iso(m["created_at"])))
    return MessageQueueOut(items=items)


@router.post("/moderation/messages/{message_id}", response_model=OkOut, dependencies=[Depends(_STAFF_LIMIT)])
async def moderate_message(message_id: uuid.UUID, body: ModerationIn, session: Session = Depends(require_staff),
                           st: AppState = Depends(state)) -> OkOut:
    async with st.db.session("admin", session.user_id) as conn:
        await conn.fetchval(_MODERATE_MESSAGE, message_id, body.decision, clean_text(body.reason or "", 300) or None, session.user_id)
    return OkOut()


@router.get("/moderation/gratitude", response_model=GratitudeQueueOut, dependencies=[Depends(_STAFF_LIMIT)])
async def gratitude_queue(session: Session = Depends(require_staff), st: AppState = Depends(state)) -> GratitudeQueueOut:
    async with st.db.session("admin", session.user_id) as conn:
        rows = await conn.fetch(_GRATITUDE_QUEUE)
    return GratitudeQueueOut(items=[
        GratitudeQueueItemOut(id=str(g["id"]), recipient_id=str(g["recipient_id"]), is_community=bool(g["is_community"]),
                              body=g["body"], created_at=iso(g["created_at"])) for g in rows])


@router.post("/moderation/gratitude/{note_id}", response_model=OkOut, dependencies=[Depends(_STAFF_LIMIT)])
async def moderate_gratitude(note_id: uuid.UUID, body: ModerationIn, session: Session = Depends(require_staff),
                             st: AppState = Depends(state)) -> OkOut:
    async with st.db.session("admin", session.user_id) as conn:
        await conn.fetchval(_MODERATE_GRATITUDE, note_id, body.decision, session.user_id)
    return OkOut()
