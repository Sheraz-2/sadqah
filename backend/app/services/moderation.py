"""Automated first-line moderation for anything one person writes to another through SadQah
(anonymous messages, thank-you notes, campaign comments).

Goal: two people who have never met, and one of whom may have chosen to stay anonymous, must not be able
to identify, contact or take money from each other outside the platform. The rules reject contact details,
off-platform handles, payment requests and probing for identity. A human staff queue exists for anything
the system moderator is not configured to approve (see MODERATION in docs/ARCHITECTURE.md).

Rules are deliberately conservative and easy to read. They are a safety net, not a substitute for the
human reviewers who handle reports.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_NUMBER_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9",
}
_URL_RE = re.compile(r"(https?://|www\.|\b[a-z0-9\-]+\.(com|net|org|io|me|co|pk|in|info|app|ly|link|xyz|ru|uk)\b)", re.I)
_EMAIL_RE = re.compile(r"[a-z0-9._%+\-]+\s*(@|\(at\)|\[at\]|\bat\b)\s*[a-z0-9\-]+\s*(\.|\(dot\)|\[dot\]|\bdot\b)\s*[a-z]{2,}", re.I)
_HANDLE_RE = re.compile(r"(?<![\w])@[a-z0-9_.]{3,}", re.I)
_PLATFORMS = ("whatsapp", "telegram", "signal app", "viber", "imo ", "wechat", "snapchat", "instagram", "facebook",
              "messenger", "skype", "tiktok", "twitter", "linkedin", "discord", "line app")
_PAYMENT_PHRASES = (
    "send money", "send me money", "western union", "moneygram", "easypaisa", "jazzcash", "bank account", "account number",
    "iban", "swift code", "paypal.me", "my paypal", "send to my", "wire transfer", "bitcoin", "crypto wallet", "gift card",
    "cash app", "venmo", "zelle", "payoneer", "transfer me", "give me your card", "card number",
)
_PROBING_PHRASES = (
    "your real name", "what is your name", "what's your name", "tell me your name", "who are you", "your address",
    "where do you live", "your phone", "your number", "your email", "your e-mail", "which city", "reveal yourself",
)
_THREAT_ABUSE = (
    "i will find you", "i'll find you", "kill you", "hurt you", "report you to", "you owe me", "you must send",
    "idiot", "bastard", "fuck", "shit",
)


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str | None = None


def _normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"\s+", " ", t)


def _digits_in(text: str) -> int:
    """Longest run of digits after spelled-out numbers are converted and separators removed."""
    words = re.sub(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b", lambda m: _NUMBER_WORDS[m.group(1)], text)
    longest = 0
    for run in re.findall(r"[0-9][0-9\s().\-_/*]{5,}[0-9]|[0-9]+", words):
        longest = max(longest, len(re.sub(r"\D", "", run)))
    return longest


def screen_text(body: str, *, min_len: int = 1, max_len: int = 1000) -> Verdict:
    text = (body or "").strip()
    if len(text) < min_len:
        return Verdict(False, "Please write a message.")
    if len(text) > max_len:
        return Verdict(False, f"Please keep it under {max_len} characters.")
    t = _normalise(text)

    if _URL_RE.search(t) or _EMAIL_RE.search(t) or _HANDLE_RE.search(t):
        return Verdict(False, "Please don't include links, e-mail addresses or usernames. Messages stay on SadQah to protect both of you.")
    if _digits_in(t) >= 7:
        return Verdict(False, "Please don't include phone numbers or long numbers.")
    if any(p in t for p in _PLATFORMS):
        return Verdict(False, "Please don't move the conversation to another app. Messages stay on SadQah to protect both of you.")
    if any(p in t for p in _PAYMENT_PHRASES):
        return Verdict(False, "Please don't ask for or share payment details. All gifts go through SadQah.")
    if any(p in t for p in _PROBING_PHRASES):
        return Verdict(False, "Please don't ask for personal details. Some donors choose to stay anonymous, and that choice is respected.")
    if any(p in t for p in _THREAT_ABUSE):
        return Verdict(False, "That message doesn't meet our kindness guidelines. Please rephrase it.")
    return Verdict(True)
