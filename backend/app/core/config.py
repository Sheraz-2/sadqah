"""Typed settings, read from the environment (and an optional .env file).

Production refuses to start with missing or development-grade secrets. In `dev` only,
missing secrets fall back to fixed, publicly known values so a laptop works out of the box.
Those values must never protect real data.
"""
from __future__ import annotations

import base64
import json
import secrets
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Publicly known development-only values. Never reuse.
_DEV_MASTER_KEY = base64.b64encode(b"restored-dev-master-key-32bytes!").decode()
_DEV_BLIND_KEY = base64.b64encode(b"restored-dev-blind-index-key-32b").decode()
_DEV_TOKEN_PEPPER = base64.b64encode(b"restored-dev-token-pepper-32byte").decode()
_DEV_JWT_SECRET = "restored-dev-jwt-secret-not-for-production-0123456789"

# Indicative exchange rates to USD, used ONLY to sanity-check the "< $50 / month" rule on
# documents in local currency. A human reviewer always confirms. Override with FX_RATES_JSON.
_DEFAULT_FX = {
    "USD": 1.0, "EUR": 1.08, "GBP": 1.27, "PKR": 0.0036, "INR": 0.012, "BDT": 0.0082, "LKR": 0.0033,
    "NPR": 0.0075, "AFN": 0.014, "NGN": 0.00065, "KES": 0.0077, "GHS": 0.065, "UGX": 0.00027,
    "TZS": 0.00037, "ETB": 0.0083, "EGP": 0.021, "PHP": 0.017, "IDR": 0.000062, "MMK": 0.00048,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # ---- general ---------------------------------------------------------------------------
    env: Literal["dev", "staging", "prod"] = "dev"
    app_base_url: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000"
    trusted_proxy_count: int = 0          # how many reverse proxies sit in front (X-Forwarded-For hops)
    log_level: str = "INFO"
    redis_url: str | None = None          # rate limiting; falls back to in-process memory in dev

    # ---- database: one least-privilege login role per service ------------------------------
    database_url_api: str = "postgresql://sadqah_api:restored_api_pw@localhost:5432/sadqah"
    database_url_worker: str = "postgresql://sadqah_worker:restored_worker_pw@localhost:5432/sadqah"
    database_url_webhook: str = "postgresql://sadqah_webhook:restored_hook_pw@localhost:5432/sadqah"
    database_url_kyc: str = "postgresql://sadqah_kyc:restored_kyc_pw@localhost:5432/sadqah"
    database_url_admin: str = "postgresql://sadqah_admin:restored_admin_pw@localhost:5432/sadqah"

    # ---- secrets ---------------------------------------------------------------------------
    encryption_keys: str | None = None        # "v1:<b64 32 bytes>,v2:<b64 32 bytes>"
    active_key_id: str = "v1"
    blind_index_key: str | None = None        # base64, 32 bytes. Rotating it requires re-indexing.
    token_pepper: str | None = None           # base64, 32 bytes. Rotating it invalidates every Donation Token.
    jwt_secret: str | None = None             # >= 32 chars
    session_ttl_minutes: int = 720
    staff_session_ttl_minutes: int = 60

    # ---- PayPal ----------------------------------------------------------------------------
    paypal_env: Literal["sandbox", "live"] = "sandbox"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_webhook_id: str = ""
    paypal_timeout_seconds: float = 20.0

    # ---- donations -------------------------------------------------------------------------
    min_donation_cents: int = Field(100, ge=100)
    max_donation_cents: int = Field(50_000, le=500_000)     # $500 default keeps gifts micro and AML-friendly
    donation_presets_cents: str = "500,1000,2500,5000"

    # ---- payout batching (Constraint 1) ----------------------------------------------------
    payout_max_items_per_batch: int = Field(500, ge=1, le=15_000)
    payout_min_items_to_fire: int = Field(25, ge=1)         # fire early once this many are ready ...
    payout_max_wait_seconds: int = Field(900, ge=0)         # ... or once the oldest has waited this long
    payout_poll_seconds: int = Field(20, ge=1)
    payout_max_attempts: int = Field(6, ge=1, le=12)
    payout_email_subject: str = "You have received a SadQah micro-grant"
    payout_email_message: str = (
        "A supporter of SadQah has sent you a small grant to help your business. "
        "If you do not have a PayPal account yet, follow the link in this message to create one and claim it."
    )
    reconcile_stale_after_seconds: int = 900

    # ---- KYC / AI --------------------------------------------------------------------------
    anthropic_api_key: str | None = None
    kyc_llm_model: str = "claude-sonnet-5-5"
    kyc_llm_max_tokens: int = 2000
    assistant_llm_model: str | None = None                 # defaults to kyc_llm_model
    assistant_max_tokens: int = 1500
    # Which engine the ASSISTANT (chat, price check, needs-proof check) uses. It is chosen explicitly and never changes by itself:
    # "anthropic" (default, the original behaviour: needs ANTHROPIC_API_KEY), "ollama" (a local model, nothing leaves your
    # machine) or "none" (built-in FAQ only). KYC document extraction and the other AI features ignore this setting.
    assistant_provider: Literal["anthropic", "ollama", "none"] = "anthropic"
    ollama_base_url: str = "http://host.docker.internal:11434"   # how the API container reaches Ollama on the host
    ollama_model: str = Field("qwen2.5:1.5b", min_length=1, max_length=100)
    ollama_timeout_seconds: float = Field(120.0, gt=0, le=600)   # small local models on a CPU can be slow
    ollama_num_ctx: int = Field(4096, ge=1024, le=32768)         # Ollama's own default (2048) would cut off the start of the prompt
    ollama_max_tokens: int = Field(400, ge=64, le=4000)          # cap on a CHAT reply (the prompt asks for ~120 words); price estimates size themselves
    ollama_keep_alive: str = Field("30m", pattern=r"^(-1|\d{1,5}[smh]?)$")   # keep the model loaded between questions (reloading costs many seconds)
    ollama_max_concurrent: int = Field(1, ge=1, le=8)            # model calls at once: a CPU model cannot go faster in parallel, it only slows the site
    ollama_max_queue: int = Field(2, ge=0, le=20)                # further calls allowed to wait; beyond this the answer is "busy", not a pile-up
    ollama_num_thread: int | None = Field(None, ge=1, le=256)    # CPU threads for the model; set below your core count to leave room for the website
    assistant_history_messages: int = Field(6, ge=1, le=14)      # newest chat messages sent to the model (a small model gains little from more)
    assistant_history_chars: int = Field(3000, ge=200, le=20000) # and a total size budget for them
    kyc_face_provider: Literal["none", "rekognition", "llm"] = "none"
    kyc_face_min_score: float = 0.85
    kyc_distress_threshold_cents: int = 5000               # mirrors the CHECK constraint in the database
    kyc_allocation_min_cents: int = 5000
    kyc_allocation_max_cents: int = 50000
    kyc_target_monthly_income_cents: int = 12000           # "exit poverty" aim used to size the plan
    kyc_max_payback_months: int = 12
    kyc_poll_seconds: int = 10
    fx_rates_json: str | None = None
    system_moderator_user_id: str | None = None            # reviewer account used by the automated moderator

    # ---- password recovery: e-mail one-time codes over SMTP (no new dependency; SMS stays off until a provider is added) ----
    smtp_host: str | None = None                           # unset = recovery by e-mail is switched off (the API says so honestly)
    smtp_port: int = Field(587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None                           # e.g. "SadQah <no-reply@your-domain>"
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    smtp_timeout_seconds: float = Field(10.0, gt=0, le=60)
    recovery_code_ttl_seconds: int = Field(900, ge=60, le=3600)
    sms_provider: str = "none"                             # only "none" exists: nothing is sent by SMS until a provider is implemented

    # ---- storage ---------------------------------------------------------------------------
    storage_backend: Literal["local", "s3"] = "local"
    vault_dir: str = "./var/vault"
    public_media_dir: str = "./var/public_media"
    s3_bucket: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    clamav_host: str | None = None                         # clamd for the malware-scan hook (recommended in prod)
    clamav_port: int = 3310
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 40_000_000

    # --------------------------------------------------------------------------------------
    @field_validator("ollama_base_url")
    @classmethod
    def _ollama_url(cls, v: str) -> str:
        parts = urlsplit(v.strip())
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError("OLLAMA_BASE_URL must look like http://host:11434")
        if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
            raise ValueError("OLLAMA_BASE_URL must be just scheme://host:port (no credentials, path or query)")
        return f"{parts.scheme}://{parts.netloc}"

    @model_validator(mode="after")
    def _secrets(self) -> Settings:
        if self.env == "dev":
            self.encryption_keys = self.encryption_keys or f"v1:{_DEV_MASTER_KEY}"
            self.blind_index_key = self.blind_index_key or _DEV_BLIND_KEY
            self.token_pepper = self.token_pepper or _DEV_TOKEN_PEPPER
            self.jwt_secret = self.jwt_secret or _DEV_JWT_SECRET
            return self

        problems: list[str] = []
        for name in ("encryption_keys", "blind_index_key", "token_pepper", "jwt_secret"):
            if not getattr(self, name):
                problems.append(f"{name.upper()} is required when ENV={self.env}")
        if self.jwt_secret and (len(self.jwt_secret) < 32 or self.jwt_secret == _DEV_JWT_SECRET):
            problems.append("JWT_SECRET must be a random string of at least 32 characters")
        for name, dev_value in (("blind_index_key", _DEV_BLIND_KEY), ("token_pepper", _DEV_TOKEN_PEPPER)):
            if getattr(self, name) == dev_value:
                problems.append(f"{name.upper()} must not be the development value")
        if self.encryption_keys and _DEV_MASTER_KEY in self.encryption_keys:
            problems.append("ENCRYPTION_KEYS must not contain the development key")
        for name in ("database_url_api", "database_url_worker", "database_url_webhook", "database_url_kyc", "database_url_admin"):
            if any(p in getattr(self, name) for p in (":restored_api_pw@", ":restored_worker_pw@", ":restored_hook_pw@", ":restored_kyc_pw@", ":restored_admin_pw@")):
                problems.append(f"{name.upper()} still uses a development password")
        if self.env == "prod" and self.paypal_env != "live":
            problems.append("PAYPAL_ENV must be 'live' in prod (this build is sandbox-oriented: set it deliberately)")
        if not (self.paypal_client_id and self.paypal_client_secret and self.paypal_webhook_id):
            problems.append("PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET and PAYPAL_WEBHOOK_ID are required")
        if not self.redis_url:
            problems.append("REDIS_URL is required so rate limits are shared between processes")
        if self.smtp_host and self.smtp_security == "none":
            problems.append("SMTP_SECURITY must be 'starttls' or 'ssl' outside dev (recovery codes must not cross the network in clear text)")
        if problems:
            raise ValueError("Unsafe configuration: " + "; ".join(problems))
        return self

    # ---- derived ---------------------------------------------------------------------------
    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.env != "dev"

    @property
    def paypal_base_url(self) -> str:
        return "https://api-m.sandbox.paypal.com" if self.paypal_env == "sandbox" else "https://api-m.paypal.com"

    @property
    def presets_cents(self) -> list[int]:
        out = [int(x) for x in self.donation_presets_cents.split(",") if x.strip()]
        return [x for x in out if self.min_donation_cents <= x <= self.max_donation_cents]

    @property
    def fx_rates(self) -> dict[str, float]:
        if self.fx_rates_json:
            return {k.upper(): float(v) for k, v in json.loads(self.fx_rates_json).items()}
        return dict(_DEFAULT_FX)

    @property
    def paypal_allows_phone_receivers(self) -> bool:
        # PayPal's Payouts sandbox does not support recipient_type PHONE (see PayPal docs).
        return self.paypal_env == "live"

    def parsed_encryption_keys(self) -> dict[str, bytes]:
        keys: dict[str, bytes] = {}
        for part in (self.encryption_keys or "").split(","):
            part = part.strip()
            if not part:
                continue
            kid, _, b64 = part.partition(":")
            keys[kid] = base64.b64decode(b64)
        return keys


@lru_cache
def get_settings() -> Settings:
    return Settings()


def generate_secret_b64(n: int = 32) -> str:
    """Helper for scripts/generate_secrets.py."""
    return base64.b64encode(secrets.token_bytes(n)).decode()
