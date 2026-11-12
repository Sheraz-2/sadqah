"""One error shape for the whole API (see docs/API_CONTRACT.md):

    {"error": {"code": "snake_case_code", "message": "Human readable", "fields": {"field": "problem"}}}

Nothing in here imports a web framework, so the module is usable from workers and tests too.
Messages are written for end users: never put SQL text, stack traces or internal ids in them.
"""
from __future__ import annotations


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict[str, str] | None = None,
                 headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers or {}

    def body(self) -> dict:
        err: dict = {"code": self.code, "message": self.message}
        if self.fields:
            err["fields"] = self.fields
        return {"error": err}


def unauthenticated(message: str = "Please sign in to continue.") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(message: str = "You do not have access to this.") -> ApiError:
    return ApiError(403, "forbidden", message)


def not_found(message: str = "We could not find that.") -> ApiError:
    return ApiError(404, "not_found", message)


def conflict(message: str) -> ApiError:
    return ApiError(409, "conflict", message)


def validation(message: str, fields: dict[str, str] | None = None) -> ApiError:
    return ApiError(422, "validation_error", message, fields)


def rate_limited(retry_after: int) -> ApiError:
    retry_after = max(1, int(retry_after))
    return ApiError(429, "rate_limited", "Too many attempts. Please wait a moment and try again.",
                    headers={"Retry-After": str(retry_after)})


def upstream_unavailable(message: str = "Our payment partner is busy right now. Please try again shortly.") -> ApiError:
    return ApiError(503, "upstream_unavailable", message)
