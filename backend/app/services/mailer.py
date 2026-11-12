"""Outgoing messages for password recovery: SMTP e-mail (standard library only) and a provider interface for SMS.

SMS is OFF. `sms_provider_for` returns a provider that refuses to send until someone adds a real one to `SMS_PROVIDERS`
(see docs in docs/PASSWORD_RECOVERY.md); nothing here ever pretends a text message was delivered.

Nothing in this module logs an address, a code, a password or the message body, and failures are reported by exception
class name only (SMTP error text can echo the recipient).
"""
from __future__ import annotations

import asyncio
import smtplib
import ssl
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from app.core.config import Settings


class MailerError(Exception):
    """E-mail could not be sent (not configured, refused, network or TLS failure). The message is safe to log."""


class SmsNotConfigured(Exception):
    """No SMS provider is configured; nothing was sent."""


# --------------------------------------------------------------------------- e-mail
def _default_smtp_factory(security: str, host: str, port: int, timeout: float):
    if security == "ssl":
        return smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
    return smtplib.SMTP(host, port, timeout=timeout)


class Mailer:
    """Sends plain-text e-mail through the SMTP server named in SMTP_* settings. `smtp_factory` is for tests."""

    def __init__(self, settings: Settings, smtp_factory: Callable[[str, str, int, float], smtplib.SMTP] | None = None) -> None:
        self._s = settings
        self._factory = smtp_factory or _default_smtp_factory

    @property
    def available(self) -> bool:
        return bool(self._s.smtp_host and self._s.smtp_from)

    async def send(self, to: str, subject: str, body: str) -> None:
        if not self.available:
            raise MailerError("e-mail delivery is not configured")
        try:
            await asyncio.to_thread(self._send_sync, to, subject, body)
        except MailerError:
            raise
        except (OSError, smtplib.SMTPException, ssl.SSLError, ValueError) as exc:  # includes timeouts and refused recipients
            raise MailerError(f"smtp failure: {type(exc).__name__}") from None

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        s = self._s
        if any(c in to for c in "\r\n") or any(c in subject for c in "\r\n"):
            raise MailerError("refusing a header containing a line break")
        msg = EmailMessage()
        msg["From"] = s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=False)
        msg["Message-ID"] = make_msgid(domain=(s.smtp_from or "sadqah.invalid").rsplit("@", 1)[-1].rstrip("> ") or "sadqah.invalid")
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(body)
        client = self._factory(s.smtp_security, s.smtp_host or "", s.smtp_port, s.smtp_timeout_seconds)
        try:
            client.ehlo()
            if s.smtp_security == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if s.smtp_username:
                client.login(s.smtp_username, s.smtp_password or "")
            client.send_message(msg)
        finally:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                pass


# --------------------------------------------------------------------------- SMS (interface only)
class SmsProvider(Protocol):
    name: str
    available: bool

    async def send(self, phone_e164: str, text: str) -> None:
        """Deliver `text` to the phone number or raise. Must never claim success it cannot confirm."""
        ...


class DisabledSms:
    name = "none"
    available = False

    async def send(self, phone_e164: str, text: str) -> None:
        raise SmsNotConfigured("no SMS provider is configured")


# Register real providers here, by the name used in SMS_PROVIDER, e.g. SMS_PROVIDERS["acme"] = lambda s: AcmeSms(s).
# Empty on purpose: the project has no SMS vendor, account or credits, and none is invented.
SMS_PROVIDERS: dict[str, Callable[[Settings], SmsProvider]] = {}


def sms_provider_for(settings: Settings) -> SmsProvider:
    factory = SMS_PROVIDERS.get((settings.sms_provider or "none").lower())
    return factory(settings) if factory else DisabledSms()
