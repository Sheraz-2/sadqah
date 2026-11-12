"""PostgreSQL access: one connection pool per least-privilege role (see database/roles.sql).

  api      web requests. Reaches data only through api.* views and functions.
  webhook  PayPal webhook handler, capture finalisation and the reconciler.
  worker   payout batching.
  kyc      KYC pipeline.
  admin    staff tools.

A process only opens the pools it needs, so a compromised API process never holds worker
or staff credentials.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import Any

import asyncpg

from app.core import errors
from app.core.config import Settings

ROLES = ("api", "webhook", "worker", "kyc", "admin")


async def _init_connection(conn: asyncpg.Connection) -> None:
    for typ in ("json", "jsonb"):
        await conn.set_type_codec(typ, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


class Database:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pools: dict[str, asyncpg.Pool] = {}

    async def open(self, roles: Iterable[str]) -> Database:
        for role in roles:
            if role not in ROLES:
                raise ValueError(f"unknown database role {role!r}")
            dsn = getattr(self._settings, f"database_url_{role}")
            self._pools[role] = await asyncpg.create_pool(
                dsn, min_size=1, max_size=10 if role == "api" else 4, init=_init_connection,
                command_timeout=30, server_settings={"application_name": f"sadqah-{role}"},
            )
        return self

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.close()
        self._pools.clear()

    def pool(self, role: str) -> asyncpg.Pool:
        try:
            return self._pools[role]
        except KeyError as exc:
            raise RuntimeError(f"database role {role!r} was not opened in this process") from exc

    @contextlib.asynccontextmanager
    async def session(self, role: str, user_id: uuid.UUID | str | None = None) -> AsyncIterator[asyncpg.Connection]:
        """A transaction on the given role. `app.current_user_id` is set LOCAL to the transaction,
        so it can never leak to the next request that reuses the pooled connection."""
        async with self.pool(role).acquire() as conn, conn.transaction():
            await conn.execute("SELECT set_config('app.current_user_id', $1, true)", str(user_id) if user_id else "")
            yield conn

    def api(self, user_id: uuid.UUID | str | None = None):
        return self.session("api", user_id)

    async def ping(self) -> bool:
        async with self.pool(next(iter(self._pools))).acquire() as conn:
            return (await conn.fetchval("SELECT 1")) == 1


def record(row: asyncpg.Record | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def records(rows: Iterable[asyncpg.Record]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def translate_db_error(exc: Exception) -> errors.ApiError | None:
    """Maps constraint and privilege errors raised by our SQL functions to API errors.
    Returns None for anything unexpected, which the caller must let propagate (-> 500, logged)."""
    msg = getattr(exc, "message", None) or str(exc)
    low = msg.lower()
    if isinstance(exc, asyncpg.UniqueViolationError):
        return errors.conflict("That already exists.")
    if isinstance(exc, asyncpg.InsufficientPrivilegeError):
        return errors.forbidden("You do not have access to this.")
    if isinstance(exc, asyncpg.ProgramLimitExceededError):
        return errors.rate_limited(3600)
    if isinstance(exc, asyncpg.InvalidAuthorizationSpecificationError):
        return errors.not_found()
    if isinstance(exc, asyncpg.InvalidParameterValueError):
        return errors.not_found() if ("not found" in low or "unknown" in low) else errors.validation(msg)
    if isinstance(exc, asyncpg.CheckViolationError):
        if "campaign" in low and ("not accepting" in low or "mismatch" in low):
            return errors.ApiError(409, "campaign_unavailable", "This campaign is not accepting gifts right now.")
        if "recipient is not verified" in low:
            return errors.ApiError(409, "campaign_unavailable", "This campaign is not accepting gifts right now.")
        # Our own business-rule messages are written to be shown to the user.
        return errors.conflict(msg)
    return None
