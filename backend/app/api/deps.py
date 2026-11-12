"""Shared FastAPI dependencies: app services, authentication, CSRF, role checks and rate limiting.

Every route module imports from here instead of reaching into `request.app.state` directly.
"""
from __future__ import annotations

import ipaddress
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from app.core import errors
from app.core.config import Settings
from app.core.crypto import Crypto
from app.core.db import Database
from app.core.rate_limit import RateLimiter
from app.core.security import CSRF_HEADER, SESSION_COOKIE, Session, csrf_matches, decode_session_token
from app.services.file_vault import FileVault
from app.services.paypal_client import PayPalClient

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
STAFF_ROLES = ("reviewer", "admin")


@dataclass
class AppState:
    settings: Settings
    db: Database
    crypto: Crypto
    vault: FileVault
    paypal: PayPalClient
    limiter: RateLimiter


def state(request: Request) -> AppState:
    return request.app.state.sq


def get_settings_dep(st: AppState = Depends(state)) -> Settings:
    return st.settings


def get_db(st: AppState = Depends(state)) -> Database:
    return st.db


def get_crypto_dep(st: AppState = Depends(state)) -> Crypto:
    return st.crypto


def get_vault(st: AppState = Depends(state)) -> FileVault:
    return st.vault


def get_paypal(st: AppState = Depends(state)) -> PayPalClient:
    return st.paypal


# --------------------------------------------------------------------------- client address
def client_ip(request: Request, trusted_proxies: int = 0) -> str:
    """The caller's address. Only trusts X-Forwarded-For hops that our own proxies added (TRUSTED_PROXY_COUNT)."""
    peer = request.client.host if request.client else "0.0.0.0"
    if trusted_proxies > 0:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(parts) >= trusted_proxies:
            candidate = parts[-trusted_proxies]
            try:
                ipaddress.ip_address(candidate)
                return candidate
            except ValueError:
                pass
    return peer


# --------------------------------------------------------------------------- rate limiting
def rate_limit(name: str, limit: int, window_seconds: int) -> Callable[..., Awaitable[None]]:
    """Dependency factory: `dependencies=[Depends(rate_limit("login", 10, 300))]`.

    Keyed by a peppered hash of the caller's address, never the raw address."""

    async def dep(request: Request, st: AppState = Depends(state)) -> None:
        ip = client_ip(request, st.settings.trusted_proxy_count)
        key = st.crypto.keyed_hash("ratelimit", f"{name}|{ip}".encode()).hex()[:32]
        decision = await st.limiter.hit(f"{name}:{key}", limit, window_seconds)
        if not decision.allowed:
            raise errors.rate_limited(decision.retry_after)

    return dep


async def limit_by_key(st: AppState, name: str, value: str, limit: int, window_seconds: int) -> None:
    """Rate limit on a value that is not the IP (e.g. an account e-mail) without storing the value."""
    key = st.crypto.keyed_hash("ratelimit", f"{name}|{value}".encode()).hex()[:32]
    decision = await st.limiter.hit(f"{name}:{key}", limit, window_seconds)
    if not decision.allowed:
        raise errors.rate_limited(decision.retry_after)


# --------------------------------------------------------------------------- authentication
def optional_session(request: Request) -> Session | None:
    """The signed-in session, or None. Cookie-authenticated writes must echo the CSRF token."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = decode_session_token(token)
    if session is None:
        return None
    if request.method not in SAFE_METHODS and not csrf_matches(session, request.headers.get(CSRF_HEADER)):
        raise errors.ApiError(403, "forbidden", "Your session could not be verified. Refresh the page and try again.")
    return session


def require_session(session: Session | None = Depends(optional_session)) -> Session:
    if session is None:
        raise errors.unauthenticated()
    return session


def require_roles(*roles: str) -> Callable[..., Session]:
    allowed = set(roles)

    def dep(session: Session = Depends(require_session)) -> Session:
        if session.role not in allowed:
            raise errors.forbidden()
        return session

    return dep


require_donor_or_any = require_session
require_recipient = require_roles("recipient")
require_staff = require_roles(*STAFF_ROLES)
require_admin = require_roles("admin")


def new_id() -> uuid.UUID:
    return uuid.uuid4()
