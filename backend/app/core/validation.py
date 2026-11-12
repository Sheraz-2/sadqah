"""Input normalisation shared by routes and scripts. Pure functions, no framework imports."""
from __future__ import annotations

import re
import secrets
import unicodedata

_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]{1,64}@[a-z0-9\-]+(\.[a-z0-9\-]+)+$")
_E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize_email(raw: str) -> str:
    email = unicodedata.normalize("NFKC", raw).strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise ValueError("Enter a valid e-mail address.")
    try:  # stricter syntax check when the optional library is installed
        from email_validator import EmailNotValidError, validate_email

        try:
            email = validate_email(email, check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError("Enter a valid e-mail address.") from exc
    except ImportError:
        pass
    return email


def normalize_phone(raw: str) -> str:
    """Returns E.164 (e.g. +923001234567) or raises ValueError."""
    cleaned = re.sub(r"[\s().\-]", "", raw.strip())
    try:
        import phonenumbers

        try:
            parsed = phonenumbers.parse(cleaned, None)
        except phonenumbers.NumberParseException as exc:
            raise ValueError("Enter the phone number with its country code, e.g. +92 300 1234567.") from exc
        if not phonenumbers.is_valid_number(parsed):
            raise ValueError("That phone number does not look valid.")
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except ImportError:
        if not _E164_RE.match(cleaned):
            raise ValueError("Enter the phone number with its country code, e.g. +92 300 1234567.") from None
        return cleaned


def normalize_nic(raw: str) -> str:
    """Identity numbers are compared in a canonical form so duplicate detection is not defeated by dashes or spaces."""
    value = re.sub(r"[^A-Za-z0-9]", "", unicodedata.normalize("NFKC", raw)).upper()
    if not 5 <= len(value) <= 24:
        raise ValueError("Enter the identity document number exactly as printed.")
    return value


def mask_nic(nic: str) -> str:
    return "*" * max(0, len(nic) - 3) + nic[-3:]


def mask_handle(kind: str, handle: str) -> str:
    if kind == "EMAIL" and "@" in handle:
        local, _, domain = handle.partition("@")
        return f"{local[:1]}{'*' * max(2, len(local) - 1)}@{domain}"
    return "*" * max(0, len(handle) - 3) + handle[-3:]


def clean_text(value: str, max_len: int) -> str:
    """Trim, normalise unicode, drop control characters. Does NOT html-escape: the frontend renders text as text."""
    text = unicodedata.normalize("NFC", value).replace("\r\n", "\n")
    text = _CONTROL_RE.sub("", text).strip()
    return text[:max_len]


def slugify(text: str, max_base: int = 50) -> str:
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:max_base].strip("-") or "friend"
    return f"{base}-{secrets.token_hex(3)}"


def cents_to_decimal_string(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(int(cents))
    return f"{sign}{cents // 100}.{cents % 100:02d}"
