"""Phase 3A: Admin > Payouts shows WHY a payout is still queued (read-only visibility; no processing change).

Layers: unit + in-process (the real route handler, a scripted DB that returns rows and records the SQL it is given). Not covered: the
real PostgreSQL query/view and RLS (the live counts were checked by the user), the browser grid.
"""
import asyncio
import contextlib
import inspect
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests import _fastapi_stub

_fastapi_stub.install()

from app.api.deps import AppState  # noqa: E402
from app.api.routes import admin as admin_routes  # noqa: E402
from app.core import errors  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.core.security import Session  # noqa: E402
from app.schemas.admin import PayoutItemOut  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
FAR = NOW + timedelta(days=3650)


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        self.db.calls.append((sql, args))
        return self.db.rows


class FakeDB:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    @contextlib.asynccontextmanager
    async def session(self, role, user_id=None):
        yield FakeConn(self)


def row(status="queued", next_attempt_at=NOW - timedelta(minutes=1), kyc_approved=True, i=1):
    return dict(id=uuid.uuid4(), donation_id=uuid.uuid4(), recipient_id=uuid.uuid4(), amount_cents=1000 + i, status=status,
                batch_id=None, paypal_transaction_status=None, failure_reason=None, queued_at=NOW - timedelta(hours=1),
                settled_at=None, next_attempt_at=next_attempt_at, db_now=NOW, kyc_approved=kyc_approved)


def call(rows, crypto, status=None):
    st = AppState(settings=Settings(env="dev"), db=FakeDB(rows), crypto=crypto, vault=None, paypal=None, limiter=RateLimiter(None))
    sess = Session(user_id=uuid.uuid4(), role="admin", csrf="c", expires_at=2**31)
    out = asyncio.run(admin_routes.payout_queue(status=status, limit=200, session=sess, st=st))
    return out, st.db


def test_next_attempt_at_is_returned_as_iso_and_other_fields_are_unchanged(crypto):
    r = row(next_attempt_at=NOW + timedelta(minutes=5), i=7)
    out, _ = call([r], crypto)
    item = out.items[0]
    assert datetime.fromisoformat(item.next_attempt_at) == NOW + timedelta(minutes=5)
    assert (item.id, item.amount_cents, item.status, item.donation_id, item.recipient_id) == (str(r["id"]), 1007, "queued", str(r["donation_id"]), str(r["recipient_id"]))
    assert item.queued_at and item.settled_at is None and item.batch_id is None


def test_future_scheduled_queued_record_is_waiting_even_when_kyc_is_approved(crypto):
    items, _ = call([row(next_attempt_at=FAR), row(next_attempt_at=NOW + timedelta(seconds=1))], crypto)
    assert [i.eligibility for i in items.items] == ["waiting", "waiting"]


def test_eligible_queued_record_is_ready(crypto):
    items, _ = call([row(next_attempt_at=NOW - timedelta(seconds=1)), row(next_attempt_at=NOW)], crypto)  # due exactly now is due
    assert [i.eligibility for i in items.items] == ["ready", "ready"]


def test_kyc_blocked_is_reported_only_from_the_kyc_data_and_takes_precedence(crypto):
    items, _ = call([row(kyc_approved=False), row(kyc_approved=False, next_attempt_at=FAR), row(kyc_approved=True)], crypto)
    assert [i.eligibility for i in items.items] == ["kyc_blocked", "kyc_blocked", "ready"]


def test_non_queued_rows_get_no_eligibility_and_keep_their_status(crypto):
    statuses = ["batched", "submitted", "succeeded", "unclaimed", "returned", "failed", "blocked", "held", "cancelled"]
    items, _ = call([row(status=s, kyc_approved=(n % 2 == 0), next_attempt_at=FAR, i=n) for n, s in enumerate(statuses)], crypto)
    assert [i.status for i in items.items] == statuses
    assert all(i.eligibility is None for i in items.items)           # never a label on a row that is not queued
    assert all(i.next_attempt_at is not None for i in items.items)   # the raw time is still shown


def test_missing_next_attempt_or_clock_never_invents_a_state():
    f = admin_routes.payout_eligibility
    assert f("queued", None, True, NOW) == "ready"                   # no schedule recorded = not waiting
    assert f("queued", FAR, True, None) == "ready"                   # cannot compare without the DB clock: do not claim "waiting"
    assert f("queued", FAR, False, None) == "kyc_blocked"
    assert f("failed", FAR, False, NOW) is None


def test_no_seed_label_is_ever_produced(crypto):
    items, _ = call([row(next_attempt_at=FAR), row()], crypto)
    assert set(PayoutItemOut.model_fields) >= {"next_attempt_at", "eligibility"}
    assert not any("seed" in str(v).lower() for i in items.items for v in i.model_dump().values())
    assert "seed" not in inspect.getsource(admin_routes.payout_eligibility).lower()


def test_queries_are_read_only_and_use_the_existing_view_and_filters(crypto):
    for status in (None, "queued"):
        _, db = call([row()], crypto, status=status)
        (sql, args), = db.calls
        assert sql.lstrip().upper().startswith("SELECT") and "core.v_admin_payout_queue" in sql
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|CREATE|DROP|fn_requeue|fn_claim)\b", sql, re.I)
        assert "q.next_attempt_at" in sql and "k.status = 'approved'" in sql and "ORDER BY q.queued_at DESC" in sql
        assert args == ((200,) if status is None else (200, "queued"))
    assert admin_routes._REQUEUE == "SELECT core.fn_requeue_payout($1, $2)"        # requeue untouched


def test_unknown_status_filter_is_still_rejected(crypto):
    with pytest.raises(errors.ApiError):
        call([row()], crypto, status="seeded")


def test_the_kyc_condition_matches_the_workers_claim_condition():
    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    worker = "EXISTS (SELECT 1 FROM core.recipients_kyc k WHERE k.recipient_id = q.recipient_id AND k.status = 'approved')"
    assert worker in admin_routes._QUEUE_ALL and worker in admin_routes._QUEUE_BY_STATUS
    claim = re.search(r"CREATE FUNCTION core\.fn_claim_payout_batch.*?\$\$;", schema, re.S).group(0)
    assert "k.recipient_id = q.recipient_id AND k.status = 'approved'" in claim and "q.next_attempt_at <= now()" in claim


needs_frontend = pytest.mark.skipif(not (ROOT / "frontend" / "src").is_dir(), reason="frontend sources are not part of this checkout")


@needs_frontend
def test_frontend_type_and_page_show_eligibility():
    types_ts = (ROOT / "frontend/src/types/admin.ts").read_text(encoding="utf-8")
    block = re.search(r"type PayoutItem = \{.*?\n\};", types_ts, re.S).group(0)
    assert "next_attempt_at: string | null;" in block and '"ready" | "waiting" | "kyc_blocked" | null' in block
    page = (ROOT / "frontend/src/app/admin/payouts/page.tsx").read_text(encoding="utf-8")
    for needle in ('"Eligibility"', '"Eligible from"', 'return "Ready"', 'return "Waiting"', "Blocked: KYC not approved"):
        assert needle in page
    assert "seed" not in page.lower()
    assert 'const STATUSES = ["queued", "batched", "submitted", "succeeded", "unclaimed", "returned", "failed", "blocked", "held", "cancelled"]' in page
    assert not re.search(r"^export (?!default)", page, re.M)   # a Next.js page may only export the page itself
