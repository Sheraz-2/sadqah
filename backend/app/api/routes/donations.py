"""Giving: create a PayPal order, capture it, and the signed-in donor's own gifts, thank-yous and giving plan.

Order of events for one gift (docs/ARCHITECTURE.md, "Money path"):
  1. the donation row (its UUID, the campaign and recipient it is bound to, and for anonymous gifts only the
     peppered HASH of the Donation Token) is committed FIRST;
  2. only then is PayPal contacted, with that UUID as `custom_id`;
  3. the donor approves in PayPal's modal and the browser asks us to capture;
  4. the capture is recorded by the webhook role. The payout itself is never started here: a database trigger
     queues it and the payout worker batches it.
The Donation Token is generated here, returned once, and never stored or logged.
"""
from __future__ import annotations

import logging
import re
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Response

from app.api.deps import AppState, limit_by_key, optional_session, rate_limit, require_session, state
from app.api.routes.public import iso
from app.core import errors
from app.core.security import Session
from app.core.validation import cents_to_decimal_string
from app.schemas.donations import (
    CaptureOut,
    CreateOrderIn,
    CreateOrderOut,
    MyDonationOut,
    MyDonationsOut,
    MyGratitudeListOut,
    MyGratitudeOut,
    PledgeIn,
    PledgeOut,
)
from app.services.paypal_client import PayPalError, amount_to_cents, first_capture
from app.services.token_service import generate_token, normalise_token
from app.services.webhook_processor import record_capture

router = APIRouter(prefix="", tags=["donations"])
log = logging.getLogger("sadqah.donations")

_ORDER_IP_LIMIT = rate_limit("order", 30, 600)
_CAPTURE_IP_LIMIT = rate_limit("capture", 60, 600)
_ORDER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{5,64}$")

_CAMPAIGN_STATE = "SELECT status, goal_cents, raised_cents FROM api.public_campaigns WHERE slug = $1"
_CREATE_DONATION = "SELECT api.fn_create_donation($1, $2, $3, $4, $5)"
_ATTACH_ORDER = "SELECT api.fn_attach_paypal_order($1, $2)"
_DONATION_BY_ORDER = "SELECT donation_id, is_anonymous, amount_cents, donation_status FROM core.fn_donation_by_order($1)"
_OWNS_DONATION = "SELECT EXISTS (SELECT 1 FROM api.my_donations WHERE id = $1)"
_MY_DONATIONS = (
    "SELECT id, campaign_slug, campaign_title, amount_cents, status, created_at, paid_out_at, thread_open "
    "FROM api.my_donations WHERE status IN ('captured', 'paid_out', 'refunded') ORDER BY created_at DESC LIMIT 200"
)
_MY_GRATITUDE = (
    "SELECT id, donation_id, recipient_name, body, created_at FROM api.my_gratitude ORDER BY created_at DESC LIMIT 100"
)
_GET_PLEDGE = "SELECT kind, percent, amount_cents, frequency, default_anonymous FROM api.my_pledge"
_SET_PLEDGE = "SELECT api.fn_set_pledge($1, $2, $3, $4, $5)"
_CLEAR_PLEDGE = "SELECT api.fn_clear_pledge()"


def _usd(cents: int) -> str:
    return f"${cents_to_decimal_string(cents)}"


def _payment_error(exc: PayPalError) -> errors.ApiError:
    """PayPal trouble on our side of the fence is a 503 (try again); a refusal of this payment is a 402."""
    if exc.retryable or exc.unknown_outcome or exc.status is None or exc.status >= 500:
        return errors.upstream_unavailable()
    return errors.ApiError(402, "payment_failed", "PayPal could not complete this payment. Nothing was charged. Please try again.")


def _points(amount_cents: int, is_anonymous: bool) -> int | None:
    """Mirrors the leaderboard trigger in schema.sql: one point per whole dollar, at least one, public gifts only."""
    return None if is_anonymous else max(1, amount_cents // 100)


# --------------------------------------------------------------------------- create an order
@router.post("/donations/orders", status_code=201, response_model=CreateOrderOut, dependencies=[Depends(_ORDER_IP_LIMIT)])
async def create_order(body: CreateOrderIn, session: Session | None = Depends(optional_session),
                       st: AppState = Depends(state)) -> CreateOrderOut:
    s = st.settings
    if not body.is_anonymous and session is None:
        raise errors.unauthenticated("Please sign in to give publicly, or choose to give anonymously.")
    if session is not None:
        await limit_by_key(st, "order-user", str(session.user_id), 20, 600)

    if not s.min_donation_cents <= body.amount_cents <= s.max_donation_cents:
        raise errors.ApiError(
            422, "amount_out_of_range", f"Please give between {_usd(s.min_donation_cents)} and {_usd(s.max_donation_cents)}.",
            {"amount_cents": f"Choose between {_usd(s.min_donation_cents)} and {_usd(s.max_donation_cents)}."},
        )

    async with st.db.api() as conn:
        campaign = await conn.fetchrow(_CAMPAIGN_STATE, body.campaign_slug)
    if campaign is None or campaign["status"] != "active":
        raise errors.ApiError(409, "campaign_unavailable", "This campaign is not accepting gifts right now.")
    remaining = int(campaign["goal_cents"]) - int(campaign["raised_cents"])
    cap = max(remaining, s.min_donation_cents)  # the last few cents may overshoot slightly rather than be impossible to give
    if body.amount_cents > cap:
        raise errors.ApiError(
            422, "amount_out_of_range", f"This campaign needs only {_usd(cap)} more.",
            {"amount_cents": f"The most you can give to this campaign is {_usd(cap)}."},
        )

    token: str | None = None
    token_hash: bytes | None = None
    if body.is_anonymous:
        token = generate_token()
        payload = normalise_token(token)
        if payload is None:  # cannot happen; refuse rather than store a hash nobody can reproduce
            raise errors.upstream_unavailable("We could not prepare your gift. Please try again.")
        token_hash = st.crypto.hash_token(payload)
    donor_id = None if (body.is_anonymous or session is None) else session.user_id

    # 1. The donation exists, bound to its recipient, BEFORE PayPal hears about it. Committed on its own.
    async with st.db.api(donor_id) as conn:
        donation_id = await conn.fetchval(_CREATE_DONATION, body.campaign_slug, body.amount_cents, body.is_anonymous,
                                          donor_id, token_hash)

    # 2. PayPal. If this fails the row stays `initiated` and is closed by core.fn_expire_stale_donations.
    try:
        order = await st.paypal.create_order(str(donation_id), body.amount_cents)
    except PayPalError as exc:
        log.warning("paypal order creation failed for donation %s: %s", donation_id, exc.short())
        raise _payment_error(exc) from None
    order_id = str(order.get("id") or "")
    if not _ORDER_ID_RE.match(order_id):
        log.error("paypal order creation returned no usable id for donation %s", donation_id)
        raise errors.upstream_unavailable()

    async with st.db.api() as conn:
        attached = await conn.fetchval(_ATTACH_ORDER, donation_id, order_id)
    if not attached:
        raise errors.conflict("This gift was already started. Please begin again.")

    return CreateOrderOut(donation_id=str(donation_id), paypal_order_id=order_id, tracking_token=token)


# --------------------------------------------------------------------------- capture
@router.post("/donations/orders/{paypal_order_id}/capture", response_model=CaptureOut,
             dependencies=[Depends(_CAPTURE_IP_LIMIT)])
async def capture_order(paypal_order_id: str, session: Session | None = Depends(optional_session),
                        st: AppState = Depends(state)) -> CaptureOut:
    if not _ORDER_ID_RE.match(paypal_order_id):
        raise errors.not_found()

    async with st.db.session("webhook") as conn:
        found = await conn.fetchrow(_DONATION_BY_ORDER, paypal_order_id)
    if found is None:
        raise errors.not_found()
    donation_id: uuid.UUID = found["donation_id"]
    anonymous = bool(found["is_anonymous"])
    expected_cents = int(found["amount_cents"])

    if not anonymous:  # a public gift can only be completed by the donor who started it
        if session is None:
            raise errors.unauthenticated()
        async with st.db.api(session.user_id) as conn:
            owns = await conn.fetchval(_OWNS_DONATION, donation_id)
        if not owns:
            raise errors.not_found()

    done = CaptureOut(donation_id=str(donation_id), amount_cents=expected_cents, is_anonymous=anonymous,
                      points_awarded=_points(expected_cents, anonymous))
    if found["donation_status"] in ("captured", "paid_out"):
        return done  # repeat call (double click, retry, or the webhook got there first)
    if found["donation_status"] != "initiated":
        raise errors.conflict("This gift can no longer be completed. Please start a new one.")

    try:
        order = await st.paypal.capture_order(paypal_order_id)
    except PayPalError as exc:
        if not exc.is_duplicate:
            log.warning("paypal capture failed for donation %s: %s", donation_id, exc.short())
            raise _payment_error(exc) from None
        try:  # PayPal says it was already captured: read the result instead
            order = await st.paypal.get_order(paypal_order_id)
        except PayPalError as exc2:
            raise _payment_error(exc2) from None

    capture = first_capture(order)
    if capture is None or str(capture.get("status")) != "COMPLETED":
        # e.g. PENDING (PayPal is reviewing it). The PAYMENT.CAPTURE.COMPLETED webhook finishes the gift if it clears.
        log.info("capture for donation %s is not complete yet", donation_id)
        raise errors.ApiError(402, "payment_failed", "PayPal is still reviewing this payment. We will finish your gift "
                                                      "automatically if it clears. You do not need to pay again.")
    amount = capture.get("amount") or {}
    try:
        cents = amount_to_cents(amount.get("value", ""))
    except ValueError:
        cents = -1
    custom_id = capture.get("custom_id")
    if amount.get("currency_code") != "USD" or cents != expected_cents or (custom_id and str(custom_id) != str(donation_id)):
        log.error("capture for donation %s does not match what was ordered", donation_id)  # never trust the client or the payload
        raise errors.conflict("This payment did not match your gift, so it was not recorded. Please contact support.")

    payer_ref = (order.get("payer") or {}).get("payer_id")
    async with st.db.session("webhook") as conn:
        await record_capture(conn, donation_id, str(capture["id"]), cents, st.crypto, str(payer_ref) if payer_ref else None)
    return done


# --------------------------------------------------------------------------- the donor's own data
@router.get("/me/donations", response_model=MyDonationsOut)
async def my_donations(session: Session = Depends(require_session), st: AppState = Depends(state)) -> MyDonationsOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_MY_DONATIONS)
    return MyDonationsOut(items=[
        MyDonationOut(
            id=str(r["id"]), campaign_slug=r["campaign_slug"], campaign_title=r["campaign_title"],
            amount_cents=int(r["amount_cents"]), status=r["status"], created_at=iso(r["created_at"]),
            paid_out_at=iso(r["paid_out_at"]) if r["paid_out_at"] else None, thread_open=bool(r["thread_open"]),
        )
        for r in rows
    ])


@router.get("/me/gratitude", response_model=MyGratitudeListOut)
async def my_gratitude(session: Session = Depends(require_session), st: AppState = Depends(state)) -> MyGratitudeListOut:
    async with st.db.api(session.user_id) as conn:
        rows = await conn.fetch(_MY_GRATITUDE)
    return MyGratitudeListOut(items=[
        MyGratitudeOut(id=str(r["id"]), donation_id=str(r["donation_id"]), recipient_name=r["recipient_name"],
                       body=r["body"], created_at=iso(r["created_at"]))
        for r in rows
    ])


def _pledge_out(row) -> PledgeOut:
    return PledgeOut(kind=row["kind"], percent=float(row["percent"]) if row["percent"] is not None else None,
                     amount_cents=int(row["amount_cents"]), frequency=row["frequency"],
                     default_anonymous=bool(row["default_anonymous"]))


@router.get("/me/pledge", response_model=PledgeOut | None)
async def get_pledge(session: Session = Depends(require_session), st: AppState = Depends(state)) -> PledgeOut | None:
    async with st.db.api(session.user_id) as conn:
        row = await conn.fetchrow(_GET_PLEDGE)
    return _pledge_out(row) if row is not None else None


@router.put("/me/pledge", response_model=PledgeOut)
async def put_pledge(body: PledgeIn, session: Session = Depends(require_session), st: AppState = Depends(state)) -> PledgeOut:
    percent = Decimal(str(body.percent)) if body.percent is not None else None
    async with st.db.api(session.user_id) as conn:
        await conn.fetchval(_SET_PLEDGE, body.kind, percent, body.amount_cents, body.frequency, body.default_anonymous)
        row = await conn.fetchrow(_GET_PLEDGE)
    return _pledge_out(row)


@router.delete("/me/pledge", status_code=204, response_class=Response)
async def delete_pledge(session: Session = Depends(require_session), st: AppState = Depends(state)) -> Response:
    async with st.db.api(session.user_id) as conn:
        await conn.fetchval(_CLEAR_PLEDGE)
    return Response(status_code=204)
