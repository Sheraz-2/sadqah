"""Thin, defensive PayPal REST client: Orders v2 (donations), Payouts (grants), webhook verification.

Reliability rules (Constraint 1):
  * Every POST carries a `PayPal-Request-Id`. Retrying a call that may already have reached PayPal is therefore
    safe: PayPal answers with the original result instead of acting twice.
  * Transient failures (timeouts, 429, 5xx) are retried in-process a few times with exponential backoff and jitter.
    If they persist the error is raised as `retryable`, and the caller schedules a much longer, persisted backoff.
  * A timeout is flagged `unknown_outcome`: the request may have been executed, so the caller must retry with
    the SAME request id and never invent a new one.
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.core.validation import cents_to_decimal_string

_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_DUPLICATE_ISSUES = {"DUPLICATE_REQUEST_ID", "DUPLICATE_INVOICE_ID", "BATCH_ALREADY_EXISTS"}


class PayPalError(Exception):
    def __init__(self, message: str, *, status: int | None = None, name: str | None = None, issue: str | None = None,
                 debug_id: str | None = None, retryable: bool = False, unknown_outcome: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.name = name
        self.issue = issue
        self.debug_id = debug_id
        self.retryable = retryable
        self.unknown_outcome = unknown_outcome

    @property
    def is_duplicate(self) -> bool:
        text = f"{self.name or ''} {self.issue or ''} {self}".lower()
        return (self.issue in _DUPLICATE_ISSUES) or "already exist" in text or "duplicate" in text

    def short(self) -> str:
        parts = [self.name or "", self.issue or "", str(self)[:200], f"debug_id={self.debug_id}" if self.debug_id else ""]
        return " | ".join(p for p in parts if p)[:480]


def amount_to_cents(value: str | int | float | Decimal) -> int:
    try:
        d = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("invalid amount") from exc
    cents = d * 100
    if cents != cents.to_integral_value():
        raise ValueError("amount has fractions of a cent")
    return int(cents)


def first_capture(order: Mapping[str, Any]) -> dict[str, Any] | None:
    units = order.get("purchase_units") or []
    if not units:
        return None
    captures = (units[0].get("payments") or {}).get("captures") or []
    return captures[0] if captures else None


class PayPalClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._http = http or httpx.AsyncClient(
            base_url=settings.paypal_base_url,
            timeout=httpx.Timeout(settings.paypal_timeout_seconds, connect=5.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth
    async def _access_token(self, force: bool = False) -> str:
        async with self._lock:
            if not force and self._token and time.monotonic() < self._token_expires - 60:
                return self._token
            try:
                resp = await self._http.post(
                    "/v1/oauth2/token", data={"grant_type": "client_credentials"},
                    auth=(self._s.paypal_client_id, self._s.paypal_client_secret), headers={"Accept": "application/json"},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise PayPalError("PayPal did not respond while signing in", retryable=True) from exc
            if resp.status_code != 200:
                raise PayPalError("PayPal rejected our credentials", status=resp.status_code,
                                  retryable=resp.status_code in _RETRYABLE_STATUS)
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires = time.monotonic() + float(data.get("expires_in", 300))
            return self._token

    # ------------------------------------------------------------------ transport with retries
    @staticmethod
    def _parse_error(resp: httpx.Response) -> PayPalError:
        name = issue = debug_id = None
        message = f"PayPal returned HTTP {resp.status_code}"
        try:
            body = resp.json()
            name = body.get("name") or body.get("error")
            message = body.get("message") or body.get("error_description") or message
            debug_id = body.get("debug_id")
            details = body.get("details") or []
            if details and isinstance(details, list) and isinstance(details[0], dict):
                issue = details[0].get("issue")
        except ValueError:
            pass
        return PayPalError(message, status=resp.status_code, name=name, issue=issue, debug_id=debug_id,
                           retryable=resp.status_code in _RETRYABLE_STATUS)

    async def _request(self, method: str, path: str, *, json_body: Any = None, request_id: str | None = None,
                       params: Mapping[str, Any] | None = None, attempts: int = 3) -> dict[str, Any]:
        last: PayPalError | None = None
        refreshed = False
        for attempt in range(attempts):
            try:
                headers = {"Authorization": f"Bearer {await self._access_token()}", "Accept": "application/json"}
                if request_id:
                    headers["PayPal-Request-Id"] = request_id
                resp = await self._http.request(method, path, json=json_body, params=params, headers=headers)
            except PayPalError as exc:
                last = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = PayPalError(f"PayPal did not respond ({type(exc).__name__})", retryable=True, unknown_outcome=True)
            else:
                if resp.status_code == 401 and not refreshed:
                    refreshed = True
                    await self._access_token(force=True)
                    continue
                if resp.status_code < 300:
                    return resp.json() if resp.content else {}
                last = self._parse_error(resp)
            if last is None or not last.retryable:
                raise last  # type: ignore[misc]
            if attempt < attempts - 1:
                await asyncio.sleep(min(8.0, 0.5 * 2**attempt) * (0.5 + random.random()))
        assert last is not None
        raise last

    # ------------------------------------------------------------------ Orders v2 (donations)
    async def create_order(self, donation_id: str, amount_cents: int) -> dict[str, Any]:
        body = {
            "intent": "CAPTURE",
            "purchase_units": [{
                "reference_id": donation_id,
                "custom_id": donation_id,                # comes back on the capture and on PAYMENT.CAPTURE.* webhooks
                "invoice_id": f"SQ-{donation_id}",
                "description": "SadQah micro-grant",
                "soft_descriptor": "SADQAH",
                "amount": {"currency_code": "USD", "value": cents_to_decimal_string(amount_cents)},
            }],
            "application_context": {
                "brand_name": "SadQah", "shipping_preference": "NO_SHIPPING", "user_action": "PAY_NOW",
                "landing_page": "NO_PREFERENCE",
            },
        }
        return await self._request("POST", "/v2/checkout/orders", json_body=body, request_id=f"order-{donation_id}")

    async def capture_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/v2/checkout/orders/{order_id}/capture", json_body={},
                                   request_id=f"capture-{order_id}")

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/v2/checkout/orders/{order_id}")

    # ------------------------------------------------------------------ Payouts (grants)
    async def create_payout_batch(self, sender_batch_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        body = {
            "sender_batch_header": {
                "sender_batch_id": sender_batch_id,
                "email_subject": self._s.payout_email_subject[:255],
                "email_message": self._s.payout_email_message[:1000],
            },
            "items": items,
        }
        # The request id equals the batch id that is already stored in our database, so a retry after a
        # timeout can never create a second batch.
        return await self._request("POST", "/v1/payments/payouts", json_body=body, request_id=sender_batch_id, attempts=3)

    async def get_payout_batch(self, payout_batch_id: str) -> dict[str, Any]:
        """The batch header plus ALL items (pages are followed)."""
        page, items, header = 1, [], {}
        while True:
            data = await self._request("GET", f"/v1/payments/payouts/{payout_batch_id}",
                                       params={"page_size": 1000, "page": page, "total_required": "true"})
            header = data.get("batch_header", header)
            items.extend(data.get("items") or [])
            if page >= int(data.get("total_pages") or 1) or page >= 20:
                return {"batch_header": header, "items": items}
            page += 1

    # ------------------------------------------------------------------ webhooks
    async def verify_webhook(self, headers: Mapping[str, str], event: dict[str, Any]) -> bool:
        needed = ("paypal-auth-algo", "paypal-cert-url", "paypal-transmission-id", "paypal-transmission-sig",
                  "paypal-transmission-time")
        values = {k: headers.get(k) for k in needed}
        if not all(values.values()):
            return False
        cert = urlparse(values["paypal-cert-url"] or "")
        if cert.scheme != "https" or not (cert.hostname or "").endswith(".paypal.com"):
            return False
        data = await self._request("POST", "/v1/notifications/verify-webhook-signature", json_body={
            "auth_algo": values["paypal-auth-algo"], "cert_url": values["paypal-cert-url"],
            "transmission_id": values["paypal-transmission-id"], "transmission_sig": values["paypal-transmission-sig"],
            "transmission_time": values["paypal-transmission-time"], "webhook_id": self._s.paypal_webhook_id,
            "webhook_event": event,
        })
        return data.get("verification_status") == "SUCCESS"
