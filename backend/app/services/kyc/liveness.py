"""Stateless selfie liveness challenge.

The applicant is shown a 4-digit code and must hold it, written on paper, in a live selfie. Nothing is stored for the
challenge itself: the token is an HMAC-signed payload (user id, expiry, random nonce) and the code is derived from the
same payload, so the server can re-derive the code when the selfie arrives. The AI pipeline later checks that the code is
visible in the photo (see fraud_scoring.liveness_code_mismatch).
Pure functions: no framework imports, testable without a database.
"""
from __future__ import annotations

import base64
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass

from app.core.crypto import Crypto

TTL_SECONDS = 15 * 60
_SIG_PURPOSE = "kyc-liveness/token"
_CODE_PURPOSE = "kyc-liveness/code"


@dataclass(frozen=True)
class Challenge:
    token: str
    code: str
    expires_at: int  # unix seconds


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _code(crypto: Crypto, payload: bytes) -> str:
    return f"{int.from_bytes(crypto.sign(_CODE_PURPOSE, payload)[:4], 'big') % 10000:04d}"


def issue(crypto: Crypto, user_id: uuid.UUID, now: float | None = None) -> Challenge:
    expires = int(time.time() if now is None else now) + TTL_SECONDS
    payload = f"{user_id}|{expires}|{secrets.token_hex(8)}".encode()
    token = f"{_b64(payload)}.{_b64(crypto.sign(_SIG_PURPOSE, payload))}"
    return Challenge(token=token, code=_code(crypto, payload), expires_at=expires)


def verify(crypto: Crypto, token: str, user_id: uuid.UUID, now: float | None = None) -> str | None:
    """Returns the 4-digit code the selfie must show, or None when the token is forged, expired or someone else's."""
    try:
        raw_payload, raw_sig = token.split(".", 1)
        payload, sig = _unb64(raw_payload), _unb64(raw_sig)
        uid, exp, _nonce = payload.decode().split("|")
        expires = int(exp)
    except (ValueError, UnicodeDecodeError):
        return None
    if not hmac.compare_digest(sig, crypto.sign(_SIG_PURPOSE, payload)):
        return None
    if uid != str(user_id) or (time.time() if now is None else now) > expires:
        return None
    return _code(crypto, payload)
