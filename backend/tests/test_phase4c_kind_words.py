"""Phase 4C: recipients see the approved PUBLIC "Kind words" comments on their own campaign(s) in the dashboard.

Layers (kept separate on purpose):
- in-process: the real route handler with a scripted DB that returns rows and records the SQL/args it is given. A scripted DB cannot
  enforce SQL semantics, so ownership/status filtering is NOT proven here.
- source guards: the SQL text, the route wiring, the frontend page.
- real PostgreSQL: database/tests/kind_words_recipient.sql proves ownership + approved-only + newest-first against the real schema,
  views and the sadqah_api role. It needs a live DB, so it is run by hand (see CHANGESET.md); here we only check that it exists and that
  its query is identical to the one the route runs.
"""
import asyncio
import contextlib
import inspect
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tests import _fastapi_stub

_fastapi_stub.install()

from app.api.deps import AppState, require_recipient  # noqa: E402
from app.api.routes import public as public_routes  # noqa: E402
from app.api.routes import recipient as recipient_routes  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.core.security import Session  # noqa: E402
from app.schemas.recipient import KindWordOut, KindWordsOut  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *args):
        self.db.calls.append((sql, args))
        return self.db.rows


class FakeDB:
    def __init__(self, rows):
        self.rows, self.calls, self.users = rows, [], []

    @contextlib.asynccontextmanager
    async def api(self, user_id=None):
        self.users.append(user_id)
        yield FakeConn(self)


def row(body, author="SadQah friend", slug="my-camp", age_h=1):
    return dict(id=uuid.uuid4(), campaign_slug=slug, author_name=author, body=body, created_at=NOW - timedelta(hours=age_h))


def call(rows, crypto):
    st = AppState(settings=Settings(env="dev"), db=FakeDB(rows), crypto=crypto, vault=None, paypal=None, limiter=RateLimiter(None))
    uid = uuid.uuid4()
    sess = Session(user_id=uid, role="recipient", csrf="c", expires_at=2**31)
    out = asyncio.run(recipient_routes.kind_words(session=sess, st=st))
    return out, st.db, uid


def flat(s):
    return re.sub(r"\s+", " ", s).strip()


# ---- handler -------------------------------------------------------------------------------------------------------------------
def test_returns_comments_in_the_order_the_query_gives_with_public_name_and_iso_date(crypto):
    out, _, _ = call([row("newer", "Ayesha", age_h=1), row("older", age_h=48)], crypto)
    assert isinstance(out, KindWordsOut)
    assert [i.body for i in out.items] == ["newer", "older"]
    assert [i.author_name for i in out.items] == ["Ayesha", "SadQah friend"]
    assert out.items[0].created_at.startswith("2026-11-09T11:00:00")
    assert all(isinstance(i, KindWordOut) for i in out.items)


def test_empty_campaign_returns_an_empty_list_not_an_error(crypto):
    out, _, _ = call([], crypto)
    assert out.items == []


def test_runs_as_the_signed_in_recipient_and_takes_no_client_input(crypto):
    out, db, uid = call([row("hello")], crypto)
    assert db.users == [uid]                                   # the GUC user comes from the session, nothing else
    assert db.calls[0][1] == ()                                # no bound parameters: no client-supplied campaign id can reach the SQL
    assert list(inspect.signature(recipient_routes.kind_words).parameters) == ["session", "st"]


def test_response_exposes_no_private_or_extra_fields():
    assert set(KindWordOut.model_fields) == {"id", "campaign_slug", "author_name", "body", "created_at"}
    assert set(KindWordsOut.model_fields) == {"items"}


# ---- SQL / wiring guards -------------------------------------------------------------------------------------------------------
def test_query_is_read_only_scoped_to_my_campaign_and_sorted_newest_first():
    q = flat(recipient_routes._KIND_WORDS)
    assert q.startswith("SELECT ")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|ALTER|DROP|TRUNCATE)\b", q, re.I)
    assert "FROM api.public_campaign_comments" in q            # the existing public (approved-only) data source
    assert "campaign_slug IN (SELECT slug FROM api.my_campaign)" in q   # ownership: the view is scoped to the session user in SQL
    assert "ORDER BY cm.created_at DESC" in q
    assert "$1" not in q                                       # no parameter


def test_query_never_touches_private_messages_or_unapproved_data():
    q = flat(recipient_routes._KIND_WORDS).lower()
    for forbidden in ("anonymous_messages", "gratitude_notes", "core.", "core.campaign_comments", "media_object_key", "author_user_id", "email"):
        assert forbidden not in q, forbidden


def test_route_is_a_recipient_only_get():
    src = (ROOT / "backend/app/api/routes/recipient.py").read_text(encoding="utf-8")
    assert '@router.get("/kind-words", response_model=KindWordsOut)' in src
    assert 'router = APIRouter(prefix="/recipient", tags=["recipient"], dependencies=[Depends(require_recipient)])' in src
    assert "session: Session = Depends(require_recipient)" in src.split("async def kind_words", 1)[1].split(")", 1)[0] + ")"
    assert require_recipient is not None


def test_sql_test_exists_and_runs_the_same_query_as_the_route():
    sql = flat((ROOT / "database/tests/kind_words_recipient.sql").read_text(encoding="utf-8"))
    assert flat(recipient_routes._KIND_WORDS.rstrip()).replace(" LIMIT 100", "") in sql
    for needle in ("a-pending", "a-rejected", "recipient B should see only their own comment", "SET LOCAL ROLE sadqah_api", "ROLLBACK;"):
        assert needle in sql


def test_public_campaign_comments_behaviour_is_unchanged():
    src = inspect.getsource(public_routes.post_comment)
    assert '"approved"' in src                                  # public comments still auto-approve exactly as before
    schema = (ROOT / "database/schema.sql").read_text(encoding="utf-8")
    view = flat(schema.split("CREATE VIEW api.public_campaign_comments", 1)[1].split(";", 1)[0])
    assert "moderation_status = 'approved'" in view or "moderation_status='approved'" in view
    assert "api.public_campaigns" in view
    assert "COALESCE(" in view and "'SadQah friend'" in view
    assert (ROOT / "frontend/src/components/campaign/CommentThread.tsx").exists()


# ---- frontend source ------------------------------------------------------------------------------------------------------------
def test_dashboard_page_has_kind_words_section_with_empty_state():
    page = (ROOT / "frontend/src/app/recipient/page.tsx").read_text(encoding="utf-8")
    assert "<KindWords />" in page
    assert ">Kind words</h2>" in page
    assert '"/recipient/kind-words"' in page
    assert "No kind words yet." in page
    assert "timeAgo(w.created_at)" in page and "w.author_name" in page
    assert "export function KindWords" not in page             # a Next page file may only export its page (and existing helpers)
    assert "campaign_slug" not in page.split("function KindWords", 1)[1]   # nothing is sent to / chosen by the client


def test_frontend_type_matches_the_api_shape():
    ts = (ROOT / "frontend/src/types/recipient.ts").read_text(encoding="utf-8")
    m = re.search(r"export type KindWord = \{(.*?)\};", ts, re.S)
    assert m
    fields = set(re.findall(r"(\w+)\s*:", m.group(1)))
    assert fields == set(KindWordOut.model_fields)
