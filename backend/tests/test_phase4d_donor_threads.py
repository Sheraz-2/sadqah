"""Phase 4D: a signed-in donor reads and writes the private thread of their own PUBLIC gifts; rejected messages no longer break responses.

Layers (kept separate on purpose):
- in-process: the real route handlers with a scripted DB that returns rows and records the SQL/args it is given. A scripted DB cannot
  enforce SQL semantics, so ownership/moderation filtering is NOT proven here.
- source guards: the patch text, route wiring, frontend source.
- real PostgreSQL: database/tests/donor_threads.sql proves ownership, moderation filtering, the delivery trigger, the daily limit and
  the grants against the real schema as sadqah_api. It needs a live DB, so it is run by hand (see CHANGESET_PHASE4D.md); here we only
  check that it exists and covers the cases.
"""
import asyncio
import contextlib
import re
import subprocess
import sys
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests import _fastapi_stub

_fastapi_stub.install()

from app.api.deps import AppState, require_roles, require_session  # noqa: E402
from app.api.routes import donor_threads as dt  # noqa: E402
from app.api.routes import public as public_routes  # noqa: E402
from app.api.routes import recipient as recipient_routes  # noqa: E402
from app.api.routes import tracking as tracking_routes  # noqa: E402
from app.core import aad, errors  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.crypto import CryptoError  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.core.security import Session  # noqa: E402
from app.schemas.donor_threads import DonorMessageOut, DonorMessagePostedOut  # noqa: E402
from app.schemas.recipient import ThreadMessageOut  # noqa: E402
from app.schemas.tracking import TrackLookupIn, TrackMessageIn, TrackMessageOut  # noqa: E402
from app.services.token_service import generate_token, normalise_token  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
DID = uuid.uuid4()
OTHER = uuid.uuid4()


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        self.db.calls.append(("fetch", sql, args))
        return self.db.script(sql, args)

    async def fetchval(self, sql, *args):
        self.db.calls.append(("fetchval", sql, args))
        return self.db.val(sql, args)


class FakeDB:
    def __init__(self, threads=(), messages=(), post_id=None, track=(), track_thread=()):
        self.threads, self.messages, self.post_id = list(threads), list(messages), post_id or uuid.uuid4()
        self.track, self.track_thread = list(track), list(track_thread)
        self.calls, self.users = [], []

    @contextlib.asynccontextmanager
    async def api(self, user_id=None):
        self.users.append(user_id)
        yield FakeConn(self)

    def script(self, sql, args):
        if "fn_my_threads" in sql:
            return self.threads
        if "fn_my_thread_messages" in sql:
            return self.messages
        if "fn_track_donation" in sql:
            return self.track
        if "fn_track_updates" in sql:
            return []
        if "fn_track_thread" in sql:
            return self.track_thread
        if "fn_recipient_thread_messages" in sql:
            return self.messages
        raise AssertionError(f"unexpected query: {sql}")

    def val(self, sql, args):
        if "fn_my_post_message" in sql or "fn_donor_post_message" in sql or "fn_recipient_post_message" in sql:
            return self.post_id
        return None

    def sqls(self, needle):
        return [c for c in self.calls if needle in c[1]]


def thread(donation_id=DID, open_=True, unread=0, status="paid_out", last=NOW):
    return dict(donation_id=donation_id, campaign_slug="camp", campaign_title="Sewing machine", recipient_name="Ana",
                donation_status=status, thread_open=open_, paid_out_at=NOW if open_ else None, last_message_at=last, unread_count=unread)


def msg(crypto, text, sender="donor", status="approved", donation_id=DID, age=1):
    return dict(id=uuid.uuid4(), sender=sender, body_enc=crypto.encrypt_text(text, aad.message(donation_id)),
                moderation_status=status, created_at=NOW - timedelta(hours=age))


def state(db, crypto):
    return AppState(settings=Settings(env="dev"), db=db, crypto=crypto, vault=None, paypal=None, limiter=RateLimiter(None))


def sess(role="donor"):
    return Session(user_id=uuid.uuid4(), role=role, csrf="c", expires_at=2**31)


def run(coro):
    return asyncio.run(coro)


# ---- who may call ---------------------------------------------------------------------------------------------------------------
def test_only_a_signed_in_donor_may_use_the_donor_routes():
    dep = require_roles("donor")
    assert dep(session=sess("donor")).role == "donor"
    for role in ("recipient", "reviewer", "admin"):
        with pytest.raises(errors.ApiError) as e:
            dep(session=sess(role))
        assert e.value.status == 403
    with pytest.raises(errors.ApiError) as e:
        require_session(None)
    assert e.value.status == 401
    src = (ROOT / "backend/app/api/routes/donor_threads.py").read_text(encoding="utf-8")
    assert 'router = APIRouter(prefix="/me", tags=["donor-threads"], dependencies=[Depends(require_donor)])' in src
    assert '"donor_threads"' in (ROOT / "backend/app/main.py").read_text(encoding="utf-8")


# ---- list -----------------------------------------------------------------------------------------------------------------------
def test_list_returns_context_unread_and_open_flag_and_runs_as_the_session_user(crypto):
    db = FakeDB(threads=[thread(unread=2), thread(donation_id=OTHER, open_=False, status="captured", last=None)])
    s = sess()
    out = run(dt.my_threads(session=s, st=state(db, crypto)))
    assert [(i.recipient_name, i.campaign_title, i.thread_open, i.unread_count) for i in out.items] == [
        ("Ana", "Sewing machine", True, 2), ("Ana", "Sewing machine", False, 0)]
    assert out.items[1].donation_status == "captured" and out.items[1].last_message_at is None and out.items[1].paid_out_at is None
    assert db.users == [s.user_id]
    assert db.calls[0][2] == ()                                  # no client-supplied parameter reaches the SQL


def test_empty_list_is_an_empty_list(crypto):
    assert run(dt.my_threads(session=sess(), st=state(FakeDB(), crypto))).items == []


# ---- read one conversation ------------------------------------------------------------------------------------------------------
def test_read_decrypts_with_donation_bound_aad_keeps_every_status_and_marks_read(crypto):
    rows = [msg(crypto, "mine pending", status="pending", age=3), msg(crypto, "mine rejected", status="rejected", age=2),
            msg(crypto, "their reply", sender="recipient", age=1)]
    db = FakeDB(threads=[thread(unread=1)], messages=rows)
    out = run(dt.my_thread(donation_id=DID, session=sess(), st=state(db, crypto)))
    assert [(m.body, m.sender, m.status) for m in out.messages] == [
        ("mine pending", "donor", "pending"), ("mine rejected", "donor", "rejected"), ("their reply", "recipient", "approved")]
    assert out.thread.unread_count == 0                           # the approved replies just shown have been read
    assert db.sqls("fn_my_mark_read")[0][2] == (DID,)
    assert db.sqls("fn_my_thread_messages")[0][2] == (DID,)


def test_a_message_bound_to_another_donation_is_skipped_not_returned(crypto):
    good, wrong = msg(crypto, "ok"), msg(crypto, "from elsewhere", donation_id=OTHER)
    out = run(dt.my_thread(donation_id=DID, session=sess(), st=state(FakeDB(threads=[thread()], messages=[wrong, good]), crypto)))
    assert [m.body for m in out.messages] == ["ok"]


def test_someone_elses_or_unknown_donation_is_a_plain_404_and_reads_nothing(crypto):
    db = FakeDB(threads=[thread(donation_id=OTHER)])              # the database lists only the caller's own threads
    with pytest.raises(errors.ApiError) as e:
        run(dt.my_thread(donation_id=DID, session=sess(), st=state(db, crypto)))
    assert e.value.status == 404
    assert not db.sqls("fn_my_thread_messages") and not db.sqls("fn_my_mark_read")


# ---- send -----------------------------------------------------------------------------------------------------------------------
def test_post_encrypts_with_donation_bound_aad_and_starts_pending_without_a_moderator(crypto):
    mid = uuid.uuid4()
    db = FakeDB(threads=[thread()], post_id=mid)
    out = run(dt.my_post_message(donation_id=DID, body=type("B", (), {"body": "Thank you so much"})(), session=sess(), st=state(db, crypto)))
    assert isinstance(out, DonorMessagePostedOut) and out.id == str(mid) and out.status == "pending"
    posted = db.sqls("fn_my_post_message")[0]
    assert posted[2][0] == DID
    assert crypto.decrypt_text(posted[2][1], aad.message(DID)) == "Thank you so much"
    with pytest.raises(CryptoError):                              # bound to this donation: another thread's AAD cannot open it
        crypto.decrypt_text(posted[2][1], aad.message(OTHER))


def test_post_to_a_gift_that_is_not_delivered_is_refused_before_anything_is_stored(crypto):
    db = FakeDB(threads=[thread(open_=False, status="captured")])
    with pytest.raises(errors.ApiError) as e:
        run(dt.my_post_message(donation_id=DID, body=type("B", (), {"body": "hello"})(), session=sess(), st=state(db, crypto)))
    assert e.value.status == 409 and e.value.message == "Messaging will open once your gift has been delivered."
    assert not db.sqls("fn_my_post_message")


def test_post_to_someone_elses_donation_is_404_and_stores_nothing(crypto):
    db = FakeDB(threads=[thread(donation_id=OTHER)])
    with pytest.raises(errors.ApiError) as e:
        run(dt.my_post_message(donation_id=DID, body=type("B", (), {"body": "hello"})(), session=sess(), st=state(db, crypto)))
    assert e.value.status == 404 and not db.sqls("fn_my_post_message")


@pytest.mark.parametrize("bad", ["write to me@example.com", "see http://x.com", "call 0300 1234567"])
def test_screening_still_blocks_contact_details(crypto, bad):
    db = FakeDB(threads=[thread()])
    with pytest.raises(errors.ApiError) as e:
        run(dt.my_post_message(donation_id=DID, body=type("B", (), {"body": bad})(), session=sess(), st=state(db, crypto)))
    assert e.value.status == 422 and not db.sqls("fn_my_post_message")


def test_existing_components_are_reused_not_copied():
    assert dt.approve_if_configured is tracking_routes.approve_if_configured
    src = (ROOT / "backend/app/api/routes/donor_threads.py").read_text(encoding="utf-8")
    for name in ("clean_text", "screen_text", "aad.message", "limit_by_key", "approve_if_configured"):
        assert name in src
    assert "def screen_text" not in src and "def clean_text" not in src


# ---- rejected messages never break a response -----------------------------------------------------------------------------------
def test_every_message_schema_accepts_rejected():
    kw = dict(id="1", sender="donor", body="x", created_at="t")
    for model in (TrackMessageOut, ThreadMessageOut, DonorMessageOut):
        assert model(status="rejected", **kw).status == "rejected"
        assert model(status="pending", **kw).status == "pending" and model(status="approved", **kw).status == "approved"
    with pytest.raises(ValidationError):
        DonorMessageOut(status="deleted", **kw)                  # still a closed set


def test_track_lookup_with_a_rejected_message_returns_it_as_rejected(crypto):
    token = generate_token()
    assert normalise_token(token)
    gift = dict(donation_id=DID, amount_cents=2500, donation_status="paid_out", delivery_state="delivered", thread_open=True,
                given_at=date(2026, 11, 1), campaign_slug="camp", campaign_title="Sewing machine", recipient_slug="ana",
                recipient_name="Ana", region_country="PK", region_admin1=None, gratitude_body=None, gratitude_at=None)
    db = FakeDB(track=[gift], track_thread=[msg(crypto, "blocked one", status="rejected", age=2), msg(crypto, "reply", sender="recipient")])
    out = run(tracking_routes.lookup(TrackLookupIn(token=token), st=state(db, crypto)))
    assert [(m.body, m.status) for m in out.messages] == [("blocked one", "rejected"), ("reply", "approved")]


def test_recipient_thread_with_a_rejected_message_returns_it_as_rejected(crypto):
    db = FakeDB(messages=[msg(crypto, "my reply", sender="recipient", status="rejected"), msg(crypto, "donor says hi")])
    out = run(recipient_routes.thread(thread_id=DID, session=sess("recipient"), st=state(db, crypto)))
    assert [(m.sender, m.status) for m in out.messages] == [("recipient", "rejected"), ("donor", "approved")]


# ---- the anonymous token door is unchanged ------------------------------------------------------------------------------------
def test_anonymous_token_message_post_still_works_and_is_donation_bound(crypto):
    token = generate_token()
    gift = dict(donation_id=DID, amount_cents=2500, donation_status="paid_out", delivery_state="delivered", thread_open=True,
                given_at=date(2026, 11, 1), campaign_slug="camp", campaign_title="t", recipient_slug="ana", recipient_name="Ana",
                region_country="PK", region_admin1=None, gratitude_body=None, gratitude_at=None)
    mid = uuid.uuid4()
    db = FakeDB(track=[gift], post_id=mid)
    out = run(tracking_routes.post_message(TrackMessageIn(token=token, body="Thanks"), st=state(db, crypto)))
    assert out.id == str(mid) and out.status == "pending"
    posted = db.sqls("fn_donor_post_message")[0]
    assert len(posted[2][0]) == 32 and crypto.decrypt_text(posted[2][1], aad.message(DID)) == "Thanks"


def test_token_functions_and_public_gift_rules_in_schema_are_untouched():
    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    assert "tracking_token_hash IS NOT NULL) OR" in schema        # anonymous gifts still require a token; public ones none is generated
    donations = (ROOT / "backend/app/api/routes/donations.py").read_text(encoding="utf-8")
    assert "if body.is_anonymous:\n        token = generate_token()" in donations


# ---- the SQL patch and its test ----------------------------------------------------------------------------------------------------
PATCH = ROOT / "database/patches/003_donor_threads.sql"


def _patch():
    return PATCH.read_text(encoding="utf-8")


def test_patch_is_the_next_sequential_additive_idempotent_patch():
    names = sorted(p.name for p in (ROOT / "database/patches").glob("*.sql"))
    assert names[:3] == ["001_account_assistant_trust.sql", "002_password_recovery.sql", "003_donor_threads.sql"]
    sql = _patch()
    assert not re.search(r"\b(DROP|TRUNCATE|DELETE FROM|ALTER TABLE|CREATE TABLE|CREATE POLICY|UPDATE core\.\w+ SET [^;]*created)", sql.replace("UPDATE core.anonymous_messages m SET read_by_donor_at", ""))
    assert sql.count("CREATE OR REPLACE FUNCTION api.fn_my_") == 4


def test_every_function_takes_the_owner_from_the_session_never_a_parameter():
    sql = _patch()
    for fn in ("fn_my_threads()", "fn_my_thread_messages(p_donation_id uuid)", "fn_my_post_message(p_donation_id uuid, p_body_enc bytea)",
               "fn_my_mark_read(p_donation_id uuid)"):
        assert f"api.{fn}" in sql
    bodies = re.split(r"CREATE OR REPLACE FUNCTION ", sql)[1:]
    assert len(bodies) == 4
    for b in bodies:
        assert "d.donor_user_id = core.current_user_id()" in b and "NOT d.is_anonymous" in b
        assert "SECURITY DEFINER" in b and "SET search_path = core, pg_catalog" in b
        assert "user_id uuid" not in b.split("AS $$")[0]          # no user id parameter
        assert "tracking_token" not in b


def test_patch_grants_only_the_four_functions_to_the_web_login_and_no_table_access():
    sql = _patch()
    assert re.search(r"GRANT EXECUTE ON FUNCTION\s+api\.fn_my_threads\(\), api\.fn_my_thread_messages\(uuid\), api\.fn_my_post_message\(uuid, bytea\), api\.fn_my_mark_read\(uuid\)\s+TO sadqah_api;", sql)
    assert sql.count("GRANT") == 1 and "ON core." not in sql.split("GRANT", 1)[1]
    assert "p_body_enc" in sql and ">= 10" in sql and "interval '24 hours'" in sql           # the same daily cap as the token door
    assert "trg_messages_before_insert" in sql                                                  # the delivery trigger is relied on, not bypassed


def test_post_function_locks_the_owned_delivered_donation_before_it_counts_and_inserts():
    sql = _patch()
    body = sql[sql.index("CREATE OR REPLACE FUNCTION api.fn_my_post_message"):sql.index("-- ---- 4.")]
    lock = body[body.index("SELECT d.id INTO v_locked"):body.index("IF NOT FOUND")]
    for cond in ("d.id = p_donation_id", "d.donor_user_id = core.current_user_id()", "NOT d.is_anonymous", "d.status = 'paid_out'", "FOR UPDATE"):
        assert cond in lock, cond
    assert "'captured'" not in lock                                       # the lock row is the DELIVERED gift only
    assert body.index("FOR UPDATE") < body.index("count(*)") < body.index("INSERT INTO core.anonymous_messages")
    assert body.index("IF NOT FOUND") < body.index("count(*)")             # not found keeps the same error, before anything is counted
    assert "invalid_authorization_specification" in body and "program_limit_exceeded" in body and ">= 10" in body and "interval '24 hours'" in body


def test_concurrency_script_exists_is_guarded_and_checks_real_overlap():
    script = ROOT / "database/tests/donor_threads_concurrency.sh"
    text = script.read_text(encoding="utf-8")
    for needle in ("ALLOW_THROWAWAY_DB", "pg_stat_activity", "wait_event_type = 'Lock'", "pg_sleep_until", "pg_sleep(3)", "exactly 10",
                   "message limit reached for today", "SET ROLE sadqah_api", "must start with exactly 9 donor messages"):
        assert needle in text, needle
    # static, on every platform: the exact opt-in guard exists and comes before any PSQL setup, temp dir or database command
    guard = ('[ "${ALLOW_THROWAWAY_DB:-}" = "1" ] || { echo "Refusing to run: this test commits data. '
             'Point it at a THROWAWAY database and set ALLOW_THROWAWAY_DB=1."; exit 2; }')
    code = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert code.count(guard) == 1
    before = code[:code.index(guard)]
    assert before == ["set -u"]
    after = "\n".join(code[code.index(guard) + 1:])
    for first_use in ("PSQL=", "mktemp", "$PSQL", "psql"):
        assert first_use in after and first_use not in "\n".join(before), first_use

    # Keep the real Bash refusal test on Unix. Windows bash may launch WSL instead.
    if sys.platform != "win32":
        out = subprocess.run(["bash", str(script)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}, timeout=20)
        assert out.returncode == 2 and "Refusing to run" in out.stdout


def test_sql_test_exists_and_covers_the_required_cases():
    sql = (ROOT / "database/tests/donor_threads.sql").read_text(encoding="utf-8")
    for needle in ("SET LOCAL ROLE sadqah_api", "ROLLBACK;", "donor 1 read donor 2", "anonymous gift thread reachable", "pending recipient reply reached the donor",
                   "posting before payout", "10-per-day limit", "mark-read did not clear", "unauthenticated session", "recipient read donor threads",
                   "wrong token found a thread", "no direct access to core.anonymous_messages"):
        assert needle in sql, needle


def test_private_messages_never_reach_public_surfaces():
    pub = (ROOT / "backend/app/api/routes/public.py").read_text(encoding="utf-8")
    assert "anonymous_messages" not in pub and "fn_my_thread" not in pub and "fn_track_thread" not in pub
    assert "anonymous_messages" not in recipient_routes._KIND_WORDS
    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    for view in re.findall(r"CREATE VIEW (api\.public_\w+) AS(.*?);", schema, re.S):
        assert "anonymous_messages" not in view[1], view[0]
    assert public_routes is not None


# ---- frontend source ------------------------------------------------------------------------------------------------------------
def test_thread_view_shows_rejected_as_not_delivered_and_types_allow_it():
    tv = (ROOT / "frontend/src/components/messaging/ThreadView.tsx").read_text(encoding="utf-8")
    assert 'status: "approved" | "pending" | "rejected"' in tv
    assert 'm.status === "rejected" && " · Not delivered"' in tv and 'm.status === "pending" && " · waiting for review"' in tv
    assert 'status: "approved" | "pending" | "rejected"' in (ROOT / "frontend/src/types/recipient.ts").read_text(encoding="utf-8")
    api_ts = (ROOT / "frontend/src/types/api.ts").read_text(encoding="utf-8")
    assert api_ts.count('"approved" | "pending" | "rejected"') >= 2


def test_donor_messages_page_and_dashboard_link():
    page = (ROOT / "frontend/src/app/dashboard/messages/page.tsx").read_text(encoding="utf-8")
    assert "Messaging will open once your gift has been delivered." in page
    assert '"/me/threads"' in page and "`/me/threads/${id}`" in page and "`/me/threads/${id}/messages`" in page
    assert 'useRequireRole("donor")' in page and 'viewerRole="donor"' in page and "ThreadView" in page
    assert "Neither side" not in page and "The recipient can see the public name on your account" in page
    assert "No conversations yet." in page and "We could not load your conversations" in page and "new</Badge>" in page
    assert re.search(r"export default function", page) and len(re.findall(r"^export ", page, re.M)) == 1   # a Next page may export only itself
    dash = (ROOT / "frontend/src/app/dashboard/page.tsx").read_text(encoding="utf-8")
    assert 'href="/dashboard/messages"' in dash and '"/me/threads"' in dash
