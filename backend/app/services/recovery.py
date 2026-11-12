"""Password recovery building blocks: one-time codes, their keyed hash, and the message text. No web framework in here.

  * Codes are 8 digits from `secrets` (cryptographically secure), shown as "1234 5678".
  * Only HMAC(server secret, e-mail + code) is stored (Crypto.sign, a key derived from the master encryption key); the
    code itself exists only in the e-mail. Binding the e-mail into the HMAC means a code cannot be replayed for another account.
  * Whether a code is right, expired, used or locked out is decided inside PostgreSQL (api.fn_pr_redeem, patch 002) under a
    row lock, so attempts cannot be raced.
"""
from __future__ import annotations

import re
import secrets

from app.core.crypto import Crypto

CODE_DIGITS = 8
_PURPOSE = "password-reset"
_NON_DIGIT = re.compile(r"[\s\-‐-―]")


def new_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))


def normalize_code(raw: str) -> str | None:
    """Accepts '1234 5678', '1234-5678' or '12345678'. Returns None for anything that is not exactly 8 ASCII digits."""
    cleaned = _NON_DIGIT.sub("", raw or "")
    return cleaned if re.fullmatch(rf"[0-9]{{{CODE_DIGITS}}}", cleaned) else None


def code_hmac(crypto: Crypto, email: str, code: str) -> bytes:
    return crypto.sign(_PURPOSE, f"{email}\x00{code}".encode())


def display_code(code: str) -> str:
    return f"{code[:4]} {code[4:]}"


def compose_email(code: str, ttl_seconds: int, base_url: str, *, by_staff: bool) -> tuple[str, str]:
    minutes = max(1, ttl_seconds // 60)
    why = ("A SadQah staff member started a password reset for your account." if by_staff
           else "Someone asked to reset the password for your SadQah account. If that was you, use the code below.")
    body = (
        f"{why}\n\n"
        f"Your one-time code: {display_code(code)}\n\n"
        f"It works once and expires in {minutes} minutes. Enter it, with your e-mail address and a new password, at:\n"
        f"{base_url.rstrip('/')}/forgot-password\n\n"
        "SadQah staff will never ask you for this code or your password. If you did not expect this e-mail, ignore it: "
        "your password has not changed.\n"
    )
    return "Your SadQah password reset code", body


def compose_sms(code: str, ttl_seconds: int) -> str:
    return f"SadQah code {display_code(code)}. Expires in {max(1, ttl_seconds // 60)} min. Never share it."
