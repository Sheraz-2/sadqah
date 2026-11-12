"""Password recovery by one-time code.

    GET  /auth/recovery/options             which channels this server can actually deliver on ({email, sms})
    POST /auth/password-reset/request       ask for a code (always the same 202 answer, whether or not the account exists)
    POST /auth/password-reset/confirm       code + new password -> 204; any failure is the same 400
    POST /admin/users/password-reset        ADMIN ONLY: send a code to a person's verified e-mail (the admin never sees it)

Rules kept here (docs/PASSWORD_RECOVERY.md has the longer version):
  * No account enumeration. `request` answers identically for known, unknown, inactive and throttled accounts, and the e-mail
    is sent after the response (background task) so timing does not differ either. `confirm` fails with one message for a
    wrong code, an expired code, a used code, a locked-out code and an unknown e-mail, and it spends one argon2 hash on every
    well-formed attempt. The only honest, non-account-specific refusals are "not configured" (503) and rate limits (429).
  * Codes: 8 digits from `secrets`, stored only as a server-keyed HMAC, expire (RECOVERY_CODE_TTL_SECONDS), work once,
    and die after 5 wrong guesses. Counting happens under a row lock inside PostgreSQL (api.fn_pr_redeem).
  * Rate limits at three layers: per client address, per e-mail (counted whether or not the account exists), and inside the
    database (60 s cooldown, 5 codes/hour per account) so they still hold if Redis is unavailable.
  * Admin-initiated resets run on the `admin` database role through core.fn_admin_start_reset, which re-checks that the actor is an
    active administrator. The code goes only to the verified e-mail on record; every attempt is audited without secrets.
  * A delivery failure closes the code, is audited, and is logged by exception class only.
  * Nothing here logs an e-mail address, code, password or hash.
Known limit: sessions are stateless JWTs, so a reset does not end sessions that are already signed in (they expire on their own).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, BackgroundTasks, Depends, Response

from app.api.deps import AppState, limit_by_key, rate_limit, require_admin, state
from app.core import aad, errors
from app.core.security import Session, hash_password, password_problem
from app.core.validation import normalize_email
from app.schemas.recovery import (
    AdminResetIn,
    AdminResetOut,
    RecoveryAcceptedOut,
    RecoveryOptionsOut,
    ResetConfirmIn,
    ResetRequestIn,
)
from app.services.mailer import Mailer, MailerError, SmsNotConfigured, sms_provider_for
from app.services.recovery import code_hmac, compose_email, compose_sms, new_code, normalize_code

router = APIRouter(tags=["recovery"])
log = logging.getLogger("sadqah.recovery")

EMAIL_INDEX = "email"  # the same blind-index purpose auth.py uses to find an account

_START = "SELECT reset_id, email_ct, phone_ct FROM api.fn_pr_start($1, $2, $3, $4)"
_REDEEM = "SELECT api.fn_pr_redeem($1, $2, $3)"
_FAILED_API = "SELECT api.fn_pr_delivery_failed($1, $2)"
_FAILED_ADMIN = "SELECT core.fn_pr_delivery_failed($1, $2)"
_ADMIN_START = "SELECT outcome, reset_id, email_ct FROM core.fn_admin_start_reset($1, $2, $3, $4)"

_REQUEST_IP_LIMIT = rate_limit("pwreset-request", 10, 3600)
_CONFIRM_IP_LIMIT = rate_limit("pwreset-confirm", 30, 900)
_OPTIONS_LIMIT = rate_limit("pwreset-options", 120, 600)
_ADMIN_LIMIT = rate_limit("admin", 300, 600)

# Worded as a promise about what happens next, never as a report that it happened: the mail is sent after this response is
# returned (background task), so at this point nothing has been delivered and nobody can yet say whether it will be.
ACCEPTED = ("If an account with that e-mail address exists, a one-time code will be sent to it shortly. "
            "It can take a few minutes to arrive. Check your spam folder too.")
BAD_CODE = "That code is not valid or has expired. Request a new code and try again."

_mailer: Mailer | None = None


def mailer_for(st: AppState) -> Mailer:
    global _mailer
    if _mailer is None:
        _mailer = Mailer(st.settings)
    return _mailer


# --------------------------------------------------------------------------- delivery (runs after the response)
async def _deliver(st: AppState, *, channel: str, reset_id: uuid.UUID, email_ct: bytes | None, phone_ct: bytes | None,
                   code: str, by_staff: bool, admin: bool) -> None:
    """Send the code; on any failure close it and record why (class name only). Never raises."""
    ttl = st.settings.recovery_code_ttl_seconds
    reason = "unknown"
    try:
        if channel == "sms":
            provider = sms_provider_for(st.settings)
            if not provider.available or phone_ct is None:
                raise SmsNotConfigured("no provider")
            phone = st.crypto.decrypt_text(phone_ct, aad.USER_PHONE)
            await provider.send(phone, compose_sms(code, ttl))
        else:
            if email_ct is None:
                raise MailerError("no address")
            to = st.crypto.decrypt_text(email_ct, aad.USER_EMAIL)
            subject, body = compose_email(code, ttl, st.settings.app_base_url, by_staff=by_staff)
            await mailer_for(st).send(to, subject, body)
        return
    except (MailerError, SmsNotConfigured) as exc:
        reason = type(exc).__name__
    except Exception as exc:  # noqa: BLE001  (a decrypt or provider bug must not become an unhandled task error)
        reason = type(exc).__name__
    log.warning("password recovery message could not be delivered (%s)", reason)
    try:
        if admin:
            async with st.db.session("admin") as conn:
                await conn.fetchval(_FAILED_ADMIN, reset_id, reason)
        else:
            async with st.db.api() as conn:
                await conn.fetchval(_FAILED_API, reset_id, reason)
    except Exception as exc:  # noqa: BLE001
        log.error("could not record a recovery delivery failure (%s)", type(exc).__name__)


# --------------------------------------------------------------------------- self-service
@router.get("/auth/recovery/options", response_model=RecoveryOptionsOut, dependencies=[Depends(_OPTIONS_LIMIT)])
async def options(st: AppState = Depends(state)) -> RecoveryOptionsOut:
    """Server-wide capability only (never account specific), so the page can say honestly when recovery is not set up."""
    return RecoveryOptionsOut(email=mailer_for(st).available, sms=sms_provider_for(st.settings).available)


@router.post("/auth/password-reset/request", status_code=202, response_model=RecoveryAcceptedOut,
             dependencies=[Depends(_REQUEST_IP_LIMIT)])
async def request_reset(body: ResetRequestIn, background: BackgroundTasks, st: AppState = Depends(state)) -> RecoveryAcceptedOut:
    if body.channel == "sms":
        if not sms_provider_for(st.settings).available:
            raise errors.ApiError(400, "channel_unavailable", "Recovery by text message is not available. Use e-mail instead.")
    elif not mailer_for(st).available:
        raise errors.upstream_unavailable("Password recovery by e-mail is not set up on this server yet. Please contact SadQah support.")

    try:
        email: str | None = normalize_email(body.email)
    except ValueError:
        email = None
    await limit_by_key(st, "pwreset-email", email or body.email.strip().lower()[:254], 3, 3600)
    if email is None:
        return RecoveryAcceptedOut(message=ACCEPTED)  # a malformed address gets the same answer as everything else

    code = new_code()
    ttl = st.settings.recovery_code_ttl_seconds
    async with st.db.api() as conn:
        row = await conn.fetchrow(_START, st.crypto.blind_index(EMAIL_INDEX, email), code_hmac(st.crypto, email, code), ttl, body.channel)
    if row is not None:
        background.add_task(_deliver, st, channel=body.channel, reset_id=row["reset_id"], email_ct=row["email_ct"],
                            phone_ct=row["phone_ct"], code=code, by_staff=False, admin=False)
    return RecoveryAcceptedOut(message=ACCEPTED)


@router.post("/auth/password-reset/confirm", status_code=204, response_class=Response, dependencies=[Depends(_CONFIRM_IP_LIMIT)])
async def confirm_reset(body: ResetConfirmIn, st: AppState = Depends(state)) -> Response:
    try:
        email: str | None = normalize_email(body.email)
    except ValueError:
        email = None
    await limit_by_key(st, "pwreset-confirm-email", email or body.email.strip().lower()[:254], 10, 900)

    problem = password_problem(body.new_password, email or body.email)
    if problem:
        raise errors.validation("Please check the highlighted fields.", {"new_password": problem})

    code = normalize_code(body.code)
    # One argon2 hash for every well-formed attempt (known account or not), so timing says nothing about the account.
    new_hash = await asyncio.to_thread(hash_password, body.new_password)
    if email is None or code is None:
        raise errors.ApiError(400, "invalid_code", BAD_CODE)
    async with st.db.api() as conn:
        ok = await conn.fetchval(_REDEEM, st.crypto.blind_index(EMAIL_INDEX, email), code_hmac(st.crypto, email, code), new_hash)
    if not ok:
        raise errors.ApiError(400, "invalid_code", BAD_CODE)
    return Response(status_code=204)


# --------------------------------------------------------------------------- admin-initiated
@router.post("/admin/users/password-reset", response_model=AdminResetOut, dependencies=[Depends(_ADMIN_LIMIT)])
async def admin_start_reset(body: AdminResetIn, background: BackgroundTasks, session: Session = Depends(require_admin),
                            st: AppState = Depends(state)) -> Any:
    """Admins only (reviewers and everyone else get 403 from `require_admin`; the database function checks again).
    The administrator learns whether a code was queued, never the code, the person's e-mail or anything about the password."""
    if not mailer_for(st).available:
        raise errors.upstream_unavailable("E-mail delivery is not configured on this server, so no reset code can be sent.")
    await limit_by_key(st, "admin-pwreset", str(session.user_id), 20, 3600)
    try:
        email = normalize_email(body.email)
    except ValueError:
        raise errors.validation("Please check the highlighted fields.", {"email": "Enter a valid e-mail address."}) from None

    code = new_code()
    try:
        async with st.db.session("admin", session.user_id) as conn:
            row = await conn.fetchrow(_ADMIN_START, session.user_id, st.crypto.blind_index(EMAIL_INDEX, email),
                                      code_hmac(st.crypto, email, code), st.settings.recovery_code_ttl_seconds)
    except asyncpg.InsufficientPrivilegeError:
        raise errors.forbidden() from None

    outcome = row["outcome"] if row is not None else "no_eligible_account"
    if outcome == "created":
        background.add_task(_deliver, st, channel="email", reset_id=row["reset_id"], email_ct=row["email_ct"], phone_ct=None,
                            code=code, by_staff=True, admin=True)
        return AdminResetOut(status="code_sent", message=(
            "A one-time code is being sent to the person's verified e-mail address. You will not see it. "
            "If they say it did not arrive, check the audit log for a delivery failure."))
    if outcome == "too_soon":
        return AdminResetOut(status="too_soon", message="A code was sent to this account very recently. Wait a minute, or ask the person to check their inbox.")
    return AdminResetOut(status="no_eligible_account", message=(
        "No active, non-administrator account with a verified e-mail address matches that address, so nothing was sent. "
        "Administrators reset their own password with \"Forgot password\"."))
