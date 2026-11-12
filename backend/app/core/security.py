"""Passwords, session tokens and CSRF.

Sessions are a signed JWT in an httpOnly cookie. The JWT also carries a random CSRF value that the
browser must echo in `X-CSRF-Token` for every cookie-authenticated write (double submit, but verified
against the signed claim rather than trusting the cookie alone).
"""
from __future__ import annotations

import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt

from app.core.config import get_settings

SESSION_COOKIE = "sq_session"
CSRF_COOKIE = "sq_csrf"
CSRF_HEADER = "x-csrf-token"
_ISSUER = "sadqah"
_STAFF_ROLES = {"reviewer", "admin"}


# ---------------------------------------------------------------- passwords (argon2id)
@lru_cache
def _hasher():
    from argon2 import PasswordHasher  # imported lazily so unit tests need no argon2

    return PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)


def hash_password(password: str) -> str:
    return _hasher().hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    from argon2.exceptions import InvalidHashError, VerificationError

    try:
        return _hasher().verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def dummy_hash() -> str:
    """Verified against when the e-mail is unknown, so login timing does not reveal which accounts exist."""
    return _hasher().hash(secrets.token_urlsafe(24))


def password_problem(password: str, email: str) -> str | None:
    if len(password) < 12:
        return "Use at least 12 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    if password.lower() == email.lower() or password.lower() in {"password1234", "123456789012", "qwertyuiop12"}:
        return "That password is too easy to guess."
    if len(set(password)) < 5:
        return "Use a more varied password."
    return None


# ---------------------------------------------------------------- sessions
@dataclass(frozen=True)
class Session:
    user_id: uuid.UUID
    role: str
    csrf: str
    expires_at: int


def session_ttl_seconds(role: str) -> int:
    s = get_settings()
    return (s.staff_session_ttl_minutes if role in _STAFF_ROLES else s.session_ttl_minutes) * 60


def create_session_token(user_id: uuid.UUID, role: str) -> tuple[str, str, int]:
    """Returns (jwt, csrf value, ttl seconds)."""
    s = get_settings()
    ttl = session_ttl_seconds(role)
    now = int(time.time())
    csrf = secrets.token_urlsafe(32)
    token = jwt.encode(
        {"sub": str(user_id), "role": role, "csrf": csrf, "iat": now, "exp": now + ttl, "iss": _ISSUER},
        s.jwt_secret, algorithm="HS256",
    )
    return token, csrf, ttl


def decode_session_token(token: str) -> Session | None:
    try:
        claims = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"], issuer=_ISSUER,
                            options={"require": ["exp", "sub", "csrf", "role"]})
        return Session(uuid.UUID(claims["sub"]), str(claims["role"]), str(claims["csrf"]), int(claims["exp"]))
    except (jwt.PyJWTError, ValueError, KeyError):
        return None


def csrf_matches(session: Session, header_value: str | None) -> bool:
    return bool(header_value) and hmac.compare_digest(session.csrf.encode(), header_value.encode())


def set_session_cookies(response, token: str, csrf: str, ttl: int) -> None:
    secure = get_settings().cookie_secure
    response.set_cookie(SESSION_COOKIE, token, max_age=ttl, httponly=True, secure=secure, samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=ttl, httponly=False, secure=secure, samesite="lax", path="/")


def clear_session_cookies(response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")
