"""GET /media/{key}: public campaign images only (uploaded through the recipient portal, already re-encoded)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app.api.deps import AppState, rate_limit, state
from app.core import errors
from app.services.file_vault import valid_key

router = APIRouter(prefix="", tags=["media"])

_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_MEDIA_LIMIT = rate_limit("media", 600, 60)


@router.get("/media/{key}", dependencies=[Depends(_MEDIA_LIMIT)])
async def get_media(key: str, st: AppState = Depends(state)) -> Response:
    ext = key.rsplit(".", 1)[1] if "." in key else ""
    content_type = _CONTENT_TYPES.get(ext)
    if not valid_key(key) or content_type is None:
        raise errors.not_found()
    data = await st.vault.get_public(key)
    if data is None:
        raise errors.not_found()
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",  # keys are random and never reused
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Content-Disposition": "inline",
        },
    )
