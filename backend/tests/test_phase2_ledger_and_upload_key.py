"""Phase 2 regression tests: (1) the admin ledger with NULL amounts, (2) the update-photo object key.

Layers: unit (schema, key helpers) and in-process integration (the REAL route handlers called directly, a scripted database, a REAL
FileVault on a temp directory, real Pillow). Not covered: real PostgreSQL / the v_admin_ledger view (see the SQL reproduction in
AUDIT_REPORT_PHASE1.md), real FastAPI request handling, the Docker volume, or the browser grid (see CHANGESET.md).
"""
import asyncio
import contextlib
import inspect
import io
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests import _fastapi_stub

_fastapi_stub.install()

from app.api import deps  # noqa: E402
from app.api.deps import AppState  # noqa: E402
from app.api.routes import admin as admin_routes  # noqa: E402
from app.api.routes import recipient as recipient_routes  # noqa: E402
from app.core import errors  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.core.security import Session  # noqa: E402
from app.schemas.admin import LedgerEventOut  # noqa: E402
from app.services.file_vault import FileVault, new_object_key, valid_key  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        self.db.calls.append(("fetch", sql, args))
        return self.db.rows

    async def fetchval(self, sql, *args):
        self.db.calls.append(("fetchval", sql, args))
        return self.db.update_id


class FakeDB:
    def __init__(self, rows=None):
        self.rows, self.calls, self.update_id = rows or [], [], uuid.uuid4()

    @contextlib.asynccontextmanager
    async def session(self, role, user_id=None):
        yield FakeConn(self)

    def api(self, user_id=None):
        return self.session("api", user_id)


# =============================================================================================== 1. ledger with NULL amounts
def ledger_row(i, event_type, amount, **kw):
    base = dict(id=i, event_type=event_type, donation_id=None, payout_queue_id=None, batch_id=None, recipient_id=None,
                amount_cents=amount, source="webhook", external_event_id=None, details={"k": i},
                created_at=datetime(2026, 11, 8, 9, 0, i % 60, tzinfo=UTC))
    base.update(kw)
    return base


def staff_session():
    return Session(user_id=uuid.uuid4(), role="admin", csrf="c", expires_at=2**31)


def call_ledger(rows, crypto):
    st = AppState(settings=Settings(env="dev"), db=FakeDB(rows), crypto=crypto, vault=None, paypal=None, limiter=RateLimiter(None))
    return run(admin_routes.ledger(after_id=None, limit=200, session=staff_session(), st=st))


def test_schema_accepts_a_missing_amount_and_still_accepts_an_amount():
    kw = dict(id=1, event_type="batch_processing", donation_id=None, payout_queue_id=None, batch_id=None, recipient_id=None,
              source=None, external_event_id=None, details=None, created_at="2026-11-08T09:00:00+00:00")
    assert LedgerEventOut(amount_cents=None, **kw).amount_cents is None
    assert LedgerEventOut(amount_cents=12500, **kw).amount_cents == 12500
    assert LedgerEventOut(amount_cents=0, **kw).amount_cents == 0          # zero is a real amount, not "missing"


def test_ledger_returns_batch_events_with_null_amounts_instead_of_crashing(crypto):
    rows = [ledger_row(4, "batch_success", None, batch_id=uuid.uuid4()),
            ledger_row(3, "batch_processing", None, batch_id=uuid.uuid4()),
            ledger_row(2, "batch_failed", None),
            ledger_row(1, "batch_denied", None)]
    out = call_ledger(rows, crypto)
    assert [e.id for e in out.items] == [4, 3, 2, 1]                        # order preserved
    assert [e.amount_cents for e in out.items] == [None, None, None, None]  # nothing invented (no 0, no guess)
    assert out.items[0].batch_id is not None and out.items[0].details == {"k": 4}


def test_ledger_still_returns_ordinary_amounts_unchanged_next_to_null_ones(crypto):
    rows = [ledger_row(5, "donation_captured", 12500, donation_id=uuid.uuid4()),
            ledger_row(4, "batch_processing", None),
            ledger_row(3, "payout_queued", 12000, payout_queue_id=uuid.uuid4()),
            ledger_row(2, "donation_captured", 0),
            ledger_row(1, "donation_captured", 7)]
    out = call_ledger(rows, crypto)
    assert [e.amount_cents for e in out.items] == [12500, None, 12000, 0, 7]
    assert all(isinstance(e.amount_cents, int) for e in out.items if e.amount_cents is not None)
    assert sum(e.amount_cents for e in out.items if e.amount_cents is not None) == 12500 + 12000 + 0 + 7  # totals unaffected
    assert out.items[0].donation_id is not None and out.items[2].payout_queue_id is not None


def test_ledger_with_no_rows_is_empty(crypto):
    assert call_ledger([], crypto).items == []


def test_ledger_handler_does_not_coalesce_a_missing_amount_to_zero():
    src = inspect.getsource(admin_routes.ledger)
    assert 'None if e["amount_cents"] is None else int(e["amount_cents"])' in src
    assert 'amount_cents=int(e["amount_cents"])' not in src


needs_frontend = pytest.mark.skipif(not (ROOT / "frontend" / "src").is_dir(), reason="frontend sources are not part of this checkout")


@needs_frontend
def test_frontend_type_and_grid_handle_a_missing_amount():
    types_ts = (ROOT / "frontend/src/types/admin.ts").read_text(encoding="utf-8")
    block = re.search(r"type LedgerEvent = \{.*?\n\};", types_ts, re.S)
    assert block and "amount_cents: number | null;" in block.group(0)
    page = (ROOT / "frontend/src/app/admin/ledger/page.tsx").read_text(encoding="utf-8")
    assert 'p.value == null ? "n/a"' in page and "formatUsd(Number(p.value), { cents: true })" in page


# =============================================================================================== 2. update-photo object key
def test_a_webp_key_generated_the_way_the_route_does_it_is_valid():
    for _ in range(50):
        key = new_object_key("webp")
        assert valid_key(key) and key.endswith(".webp") and ".." not in key and len(key) == 32 + len(".webp")


def test_leading_dot_argument_is_the_defect_it_produces_an_invalid_key():
    # documents WHY the caller must pass "webp": the vault adds the dot itself
    bad = new_object_key(".webp")
    assert ".." in bad and not valid_key(bad)


def test_recipient_route_passes_the_extension_without_a_dot():
    src = inspect.getsource(recipient_routes.post_update)
    assert 'new_object_key("webp")' in src and 'new_object_key(".webp")' not in src
    assert not re.search(r'new_object_key\(\s*["\']\.', (ROOT / "backend/app/api/routes/recipient.py").read_text(encoding="utf-8"))


def png_bytes(size=(8, 6), colour=(200, 30, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "PNG")
    return buf.getvalue()


class FakeUpload:
    def __init__(self, data):
        self._data = data

    async def read(self, n=-1):
        return self._data if n < 0 else self._data[:n]


@pytest.fixture()
def upload_env(tmp_path, crypto):
    s = Settings(env="dev", vault_dir=str(tmp_path / "vault"), public_media_dir=str(tmp_path / "public"))
    db = FakeDB()
    st = AppState(settings=s, db=db, crypto=crypto, vault=FileVault(s, crypto), paypal=None, limiter=RateLimiter(None))
    return st, db, tmp_path


def recipient_session():
    return Session(user_id=uuid.uuid4(), role="recipient", csrf="c", expires_at=2**31)


def test_update_with_photos_is_stored_by_the_vault_through_the_real_route(upload_env):
    st, db, tmp = upload_env
    out = run(recipient_routes.post_update(body="Roof is repaired, thank you.", visibility="public",
                                           images=[FakeUpload(png_bytes()), FakeUpload(png_bytes(colour=(0, 90, 200)))],
                                           session=recipient_session(), st=st))
    assert out.id == str(db.update_id)
    (_, sql, args), = [c for c in db.calls if c[0] == "fetchval"]
    assert "fn_post_campaign_update" in sql
    text, keys, visibility = args
    assert text == "Roof is repaired, thank you." and visibility == "public" and len(keys) == 2 and len(set(keys)) == 2
    for key in keys:
        assert valid_key(key) and key.endswith(".webp")
        stored = tmp / "public" / key[:2] / key
        assert stored.is_file()                                           # really written to the public media dir
        assert stored.read_bytes()[:4] == b"RIFF" and stored.read_bytes()[8:12] == b"WEBP"   # re-encoded, not the raw upload
        assert run(st.vault.public_path(key)) == stored                   # and the vault can serve it back (what /media uses)
    assert not (tmp / "vault").exists() or not any((tmp / "vault").rglob("*.webp"))   # photos never go to the private vault


def test_update_without_photos_still_works(upload_env):
    st, db, _ = upload_env
    run(recipient_routes.post_update(body="Small update", visibility="donors", images=[], session=recipient_session(), st=st))
    assert [c for c in db.calls if c[0] == "fetchval"][0][2][1] == []


def test_validation_is_unchanged_non_image_too_many_and_oversize_are_rejected(upload_env):
    st, db, tmp = upload_env
    cases = [
        [FakeUpload(b"<?php echo 1; ?>" + b"x" * 64)],                                             # not an image (magic bytes)
        [FakeUpload(png_bytes()) for _ in range(recipient_routes.MAX_IMAGES + 1)],                  # too many
        [FakeUpload(png_bytes() + b"0" * (st.settings.max_upload_bytes + 1))],                      # too large
    ]
    for images in cases:
        with pytest.raises(errors.ApiError):
            run(recipient_routes.post_update(body="x", visibility="public", images=images, session=recipient_session(), st=st))
    assert not [c for c in db.calls if c[0] == "fetchval"]                 # nothing recorded
    assert not (tmp / "public").exists() or not any((tmp / "public").rglob("*"))   # nothing written


def test_vault_still_refuses_an_invalid_key():
    # the key check in the vault was not loosened to make the route pass
    s = Settings(env="dev")
    v = FileVault(s, None)
    with pytest.raises(ValueError):
        run(v.put_public(new_object_key(".webp"), b"x"))
    for bad in ("../etc/passwd", "a" * 31 + ".webp", "A" * 32 + ".webp", "a" * 32 + ".webpwebp", "a" * 32 + "..webp"):
        assert not valid_key(bad)


def test_update_photo_authorisation_is_unchanged():
    assert inspect.signature(recipient_routes.post_update).parameters["session"].default.dependency is deps.require_recipient
    for role in ("donor", "admin", "reviewer"):
        with pytest.raises(errors.ApiError) as exc:
            deps.require_recipient(Session(user_id=uuid.uuid4(), role=role, csrf="c", expires_at=2**31))
        assert exc.value.status == 403
    ok = Session(user_id=uuid.uuid4(), role="recipient", csrf="c", expires_at=2**31)
    assert deps.require_recipient(ok) is ok
