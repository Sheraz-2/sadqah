"""Donation Tokens.

Format:  SQ-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-CCCC
  * 32 base32 characters = 160 bits from the OS random source (not guessable, not enumerable)
  * a 4 character checksum so typing mistakes are caught before any database lookup
  * dashes, spaces and case are ignored when the donor types it back

Only HMAC-SHA256(pepper, token) is stored (see Crypto.hash_token). The token itself exists in exactly
one place: the donor's screen at the moment of giving. It cannot be recovered by us, by design.
"""
from __future__ import annotations

import base64
import hashlib
import re
import secrets

_PREFIX = "SQ"
_BODY_LEN = 32
_CHECK_LEN = 4
_ALPHABET = re.compile(r"^[A-Z2-7]+$")


def _checksum(body: str) -> str:
    digest = hashlib.sha256(b"sadqah-token-check\x00" + body.encode()).digest()[:3]
    return base64.b32encode(digest).decode()[:_CHECK_LEN]


def generate_token() -> str:
    body = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    groups = [body[i : i + 4] for i in range(0, _BODY_LEN, 4)] + [_checksum(body)]
    return f"{_PREFIX}-" + "-".join(groups)


def normalise_token(raw: str) -> str | None:
    """Returns the canonical 32 character body, or None when the input cannot be a valid token."""
    if not isinstance(raw, str) or len(raw) > 80:
        return None
    compact = re.sub(r"[\s\-]", "", raw).upper()
    if not compact.startswith(_PREFIX) or len(compact) != len(_PREFIX) + _BODY_LEN + _CHECK_LEN:
        return None
    body = compact[len(_PREFIX) : len(_PREFIX) + _BODY_LEN]
    check = compact[-_CHECK_LEN:]
    if not _ALPHABET.match(body) or not _ALPHABET.match(check):
        return None
    import hmac

    return body if hmac.compare_digest(check, _checksum(body)) else None
