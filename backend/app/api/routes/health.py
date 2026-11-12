"""Liveness and readiness probes (mounted under /api/v1 like every other module)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import AppState, state
from app.core import errors

router = APIRouter(prefix="", tags=["health"])
log = logging.getLogger("sadqah.health")


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """The process is up. Never touches the database, so an orchestrator does not restart it for a database blip."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(st: AppState = Depends(state)) -> dict[str, str]:
    """Ready to serve: the database answers."""
    try:
        ok = await st.db.ping()
    except Exception:  # any failure means "not ready"; the reason stays in the log, not in the response
        log.warning("readiness check: database unreachable")
        ok = False
    if not ok:
        raise errors.ApiError(503, "upstream_unavailable", "The service is starting up or its database is unreachable.")
    return {"status": "ready"}
