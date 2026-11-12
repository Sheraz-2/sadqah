"""Authentication and account routes (docs/API_CONTRACT.md, "Auth and account").

    POST   /auth/register   201 {user: Me} + session cookies
    POST   /auth/login      200 {user: Me} + session cookies
    POST   /auth/logout     204, cookies cleared
    GET    /auth/me         Me (401 without a valid session)
    PATCH  /me              Me   ({display_name?, show_on_leaderboard?})

Conventions fixed here (do not change once real accounts exist, they would need re-indexing):
  * Blind-index purposes: e-mail -> "email" over `normalize_email(...)`, phone -> "phone" over `normalize_phone(...)`.
  * E-mail and phone are stored encrypted (aad.USER_EMAIL / aad.USER_PHONE) and looked up only by blind index.

Security notes:
  * Bad credentials, unknown e-mail, locked and deactivated accounts all produce the same 401 and message, and every
    one of those paths spends an argon2 verification (a dummy hash when there is no real one) so timing does not
    reveal whether an account exists. Hashing runs in a worker thread so it never stalls the event loop.
  * Register and login are rate limited per client address (dependency) and per e-mail (`limit_by_key`).
  * Cookies are only ever set or cleared through app.core.security helpers. CSRF is enforced by `optional_session` /
    `require_session` for every non-GET request that carries a session cookie (logout, PATCH /me).
  * Nothing here logs an e-mail, phone, password, hash or token.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from app.api.deps import AppState, limit_by_key, optional_session, rate_limit, require_session, state
from app.core import aad, errors
from app.core.security import (
    Session,
    clear_session_cookies,
    create_session_token,
    dummy_hash,
    hash_password,
    password_problem,
    set_session_cookies,
    verify_password,
)
from app.core.validation import clean_text, normalize_email, normalize_phone
from app.schemas.auth import (
    DISPLAY_NAME_MAX,
    DISPLAY_NAME_MIN,
    LoginRequest,
    MeOut,
    RegisterRequest,
    UpdateMeRequest,
    UserEnvelope,
)

router = APIRouter(prefix="", tags=["auth"])

EMAIL_INDEX = "email"
PHONE_INDEX = "phone"

_REGISTER_USER = "SELECT api.fn_register_user($1, $2, $3, $4, $5, $6, $7, $8)"
_GET_AUTH_USER = (
    "SELECT id, role, password_hash, is_active, locked_until FROM api.fn_auth_get_user($1)"
)
_RECORD_LOGIN = "SELECT api.fn_auth_record_login($1, $2)"
_GET_ME = "SELECT id, role, email_enc, phone_enc, display_name, country_code FROM api.fn_get_me()"
_GET_LEADERBOARD_PREF = "SELECT show_publicly FROM api.my_leaderboard_pref"
_SET_DISPLAY_NAME = "SELECT api.fn_set_display_name($1)"
_SET_LEADERBOARD = "SELECT api.fn_set_leaderboard_visibility($1)"

_REGISTER_IP_LIMIT = rate_limit("register", 10, 3600)
_LOGIN_IP_LIMIT = rate_limit("login", 30, 900)

_DUPLICATE_MESSAGE = "We could not create an account with those details. If you already have one, try signing in."


# --------------------------------------------------------------------------- helpers
def _bad_credentials() -> errors.ApiError:
    return errors.unauthenticated("That e-mail and password do not match.")


def _clean_display_name(raw: str | None) -> str | None:
    """None or blank clears the name. Otherwise 2 to 40 characters (users_display_name_len)."""
    if raw is None:
        return None
    text = clean_text(raw, 200)
    if not text:
        return None
    if not DISPLAY_NAME_MIN <= len(text) <= DISPLAY_NAME_MAX:
        raise ValueError(f"Use between {DISPLAY_NAME_MIN} and {DISPLAY_NAME_MAX} characters.")
    return text


def _stale_session() -> JSONResponse:
    """The cookie is signed and unexpired but the account is gone, deactivated or its role changed."""
    response = JSONResponse(errors.unauthenticated().body(), status_code=401)
    clear_session_cookies(response)
    return response


async def _load_me(st: AppState, user_id: uuid.UUID) -> MeOut | None:
    """The signed-in person's own profile. E-mail and phone are decrypted here and nowhere else."""
    async with st.db.api(user_id) as conn:
        row = await conn.fetchrow(_GET_ME)
        if row is None:
            return None
        show = await conn.fetchval(_GET_LEADERBOARD_PREF)
    phone_enc = row["phone_enc"]
    return MeOut(
        id=str(row["id"]),
        role=row["role"],
        email=st.crypto.decrypt_text(row["email_enc"], aad.USER_EMAIL),
        phone=st.crypto.decrypt_text(phone_enc, aad.USER_PHONE) if phone_enc is not None else None,
        display_name=row["display_name"],
        country_code=row["country_code"],
        show_on_leaderboard=True if show is None else bool(show),
    )


# --------------------------------------------------------------------------- register
@router.post("/auth/register", status_code=201, response_model=UserEnvelope, dependencies=[Depends(_REGISTER_IP_LIMIT)])
async def register(body: RegisterRequest, response: Response, st: AppState = Depends(state)) -> UserEnvelope:
    fields: dict[str, str] = {}

    email = ""
    try:
        email = normalize_email(body.email)
    except ValueError as exc:
        fields["email"] = str(exc)

    phone: str | None = None
    if body.phone is not None and body.phone.strip():
        try:
            phone = normalize_phone(body.phone)
        except ValueError as exc:
            fields["phone"] = str(exc)

    display_name: str | None = None
    try:
        display_name = _clean_display_name(body.display_name)
    except ValueError as exc:
        fields["display_name"] = str(exc)

    problem = password_problem(body.password, email or body.email)
    if problem:
        fields["password"] = problem

    if fields:
        raise errors.validation("Please check the highlighted fields.", fields)

    country = body.country_code.upper() if body.country_code else None

    await limit_by_key(st, "register-email", email, 5, 3600)

    # Hash before touching the database so a duplicate e-mail costs the same time as a new one.
    password_hash = await asyncio.to_thread(hash_password, body.password)

    crypto = st.crypto
    try:
        async with st.db.api() as conn:
            new_id = await conn.fetchval(
                _REGISTER_USER,
                crypto.encrypt_text(email, aad.USER_EMAIL),
                crypto.blind_index(EMAIL_INDEX, email),
                crypto.encrypt_text(phone, aad.USER_PHONE) if phone else None,
                crypto.blind_index(PHONE_INDEX, phone) if phone else None,
                password_hash,
                body.role,
                display_name,
                country,
            )
    except asyncpg.UniqueViolationError:
        # Same answer whether the e-mail or the phone number is taken, and it never says which.
        raise errors.conflict(_DUPLICATE_MESSAGE) from None

    user_id = uuid.UUID(str(new_id))
    token, csrf, ttl = create_session_token(user_id, body.role)
    set_session_cookies(response, token, csrf, ttl)
    return UserEnvelope(
        user=MeOut(
            id=str(user_id), role=body.role, email=email, phone=phone, display_name=display_name,
            country_code=country, show_on_leaderboard=True,  # a new donor is on the leaderboard until they opt out
        )
    )


# --------------------------------------------------------------------------- login / logout
@router.post("/auth/login", response_model=UserEnvelope, dependencies=[Depends(_LOGIN_IP_LIMIT)])
async def login(body: LoginRequest, response: Response, st: AppState = Depends(state)) -> UserEnvelope:
    try:
        email: str | None = normalize_email(body.email)
    except ValueError:
        email = None
    await limit_by_key(st, "login-email", email or body.email.strip().lower()[:254], 10, 900)

    row = None
    if email is not None:
        async with st.db.api() as conn:
            row = await conn.fetchrow(_GET_AUTH_USER, st.crypto.blind_index(EMAIL_INDEX, email))

    # Always spend one argon2 verification, against a throwaway hash when there is no account.
    stored_hash = row["password_hash"] if row is not None else await asyncio.to_thread(dummy_hash)
    password_ok = await asyncio.to_thread(verify_password, stored_hash, body.password)

    if row is None:
        raise _bad_credentials()
    locked = row["locked_until"] is not None and row["locked_until"] > datetime.now(UTC)
    if locked or not row["is_active"]:
        raise _bad_credentials()  # not recorded, so repeated attempts cannot extend someone's lock

    # Record the outcome in its own committed transaction (raising inside it would roll the failure count back).
    async with st.db.api() as conn:
        await conn.execute(_RECORD_LOGIN, row["id"], password_ok)
    if not password_ok:
        raise _bad_credentials()

    user_id = uuid.UUID(str(row["id"]))
    me = await _load_me(st, user_id)
    if me is None:
        raise _bad_credentials()
    token, csrf, ttl = create_session_token(user_id, me.role)
    set_session_cookies(response, token, csrf, ttl)
    return UserEnvelope(user=me)


@router.post("/auth/logout", status_code=204, response_class=Response)
async def logout(_session: Session | None = Depends(optional_session)) -> Response:
    """Idempotent. A valid session cookie without the matching X-CSRF-Token header is rejected (403) by the dependency."""
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


# --------------------------------------------------------------------------- the signed-in person
@router.get("/auth/me", response_model=MeOut)
async def auth_me(session: Session = Depends(require_session), st: AppState = Depends(state)) -> Any:
    me = await _load_me(st, session.user_id)
    if me is None or me.role != session.role:
        return _stale_session()
    return me


@router.patch("/me", response_model=MeOut)
async def update_me(body: UpdateMeRequest, session: Session = Depends(require_session),
                    st: AppState = Depends(state)) -> Any:
    change_name = "display_name" in body.model_fields_set
    display_name: str | None = None
    if change_name:
        try:
            display_name = _clean_display_name(body.display_name)
        except ValueError as exc:
            raise errors.validation("Please check the highlighted fields.", {"display_name": str(exc)}) from None

    if change_name or body.show_on_leaderboard is not None:
        async with st.db.api(session.user_id) as conn:
            if change_name:
                await conn.execute(_SET_DISPLAY_NAME, display_name)
            if body.show_on_leaderboard is not None:
                await conn.execute(_SET_LEADERBOARD, body.show_on_leaderboard)

    me = await _load_me(st, session.user_id)
    if me is None or me.role != session.role:
        return _stale_session()
    return me
