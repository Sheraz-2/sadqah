"""SadQah API application factory.

Run:  uvicorn app.main:app --host 0.0.0.0 --port 8000
Route modules live in app/api/routes/. Each exposes `router`; add a module name to ROUTE_MODULES to mount it.
"""
from __future__ import annotations

import importlib
import logging
import uuid
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.deps import AppState
from app.core import errors
from app.core.config import get_settings
from app.core.crypto import get_crypto
from app.core.db import Database, translate_db_error
from app.core.rate_limit import RateLimiter
from app.services.file_vault import FileVault
from app.services.paypal_client import PayPalClient

log = logging.getLogger("sadqah.api")

API_PREFIX = "/api/v1"
# Mounted under /api/v1 (webhooks and health are mounted at the root of /api/v1 as well; see docs/API_CONTRACT.md).
ROUTE_MODULES = (
    "health", "public", "auth", "donations", "tracking",
    "recipient", "kyc", "admin", "webhooks", "media",
    "account", "assistant", "trust", "admin_extra", "recovery", "donor_threads",
)
MAX_BODY_BYTES = 12 * 1024 * 1024  # a 10 MB upload plus multipart overhead


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    crypto = get_crypto()
    db = await Database(settings).open(["api", "webhook", "admin"])
    app.state.sq = AppState(
        settings=settings, db=db, crypto=crypto, vault=FileVault(settings, crypto),
        paypal=PayPalClient(settings), limiter=RateLimiter(settings.redis_url),
    )
    try:
        yield
    finally:
        await app.state.sq.paypal.aclose()
        await app.state.sq.limiter.close()
        await db.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="SadQah API", version="0.1.0", lifespan=lifespan,
        docs_url="/api/docs" if settings.env == "dev" else None,
        redoc_url=None, openapi_url="/api/openapi.json" if settings.env == "dev" else None,
    )

    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "X-CSRF-Token"],
        max_age=600,
    )

    @app.middleware("http")
    async def hardening(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
            return JSONResponse(errors.ApiError(413, "validation_error", "That upload is too large.").body(), status_code=413)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Request-Id", uuid.uuid4().hex[:16])
        return response

    @app.exception_handler(errors.ApiError)
    async def api_error(_: Request, exc: errors.ApiError):
        return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, exc: RequestValidationError):
        fields: dict[str, str] = {}
        for err in exc.errors():
            loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path")]
            fields[".".join(loc) or "request"] = str(err.get("msg", "Invalid value"))
        return JSONResponse(errors.validation("Please check the highlighted fields.", fields).body(), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 401: "unauthenticated", 403: "forbidden", 405: "not_found"}.get(exc.status_code, "error")
        return JSONResponse({"error": {"code": code, "message": "We could not find that." if exc.status_code in (404, 405) else str(exc.detail)}},
                            status_code=exc.status_code)

    @app.exception_handler(asyncpg.PostgresError)
    async def db_error(_: Request, exc: asyncpg.PostgresError):
        mapped = translate_db_error(exc)
        if mapped is None:
            log.exception("unexpected database error", exc_info=exc)
            return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong on our side."}}, status_code=500)
        return JSONResponse(mapped.body(), status_code=mapped.status, headers=mapped.headers)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        log.exception("unhandled error", exc_info=exc)
        return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong on our side."}}, status_code=500)

    for name in ROUTE_MODULES:
        try:
            module = importlib.import_module(f"app.api.routes.{name}")
        except ModuleNotFoundError as exc:
            if exc.name == f"app.api.routes.{name}":
                log.warning("route module %s is not present; skipping", name)
                continue
            raise
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
