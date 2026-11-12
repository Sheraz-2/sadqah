"""Password recovery: code generation and hashing, SMTP delivery and its failures, the disabled SMS interface, and the route
handlers themselves (enumeration, rate limits, authorisation, single-use, delivery failure) with a scripted database.

What these tests do NOT cover: real PostgreSQL behaviour (see database/tests/password_recovery.sql, which tests expiry, single
use, attempt limits, grants and audit rows against a real database), a real SMTP server, real argon2, or real FastAPI request
handling (route handlers are called directly; background tasks use Starlette's real BackgroundTasks). See docs/PASSWORD_RECOVERY.md.
"""
import asyncio
import contextlib
import inspect
import logging
import re
import smtplib
import types
import uuid

import pytest

from tests import _fastapi_stub

_fastapi_stub.install()

from app.api import deps  # noqa: E402
from app.api.deps import AppState  # noqa: E402
from app.api.routes import recovery as routes  # noqa: E402
from app.core import aad, errors  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.core.rate_limit import RateLimiter  # noqa: E402
from app.core.security import Session  # noqa: E402
from app.schemas.recovery import AdminResetIn, ResetConfirmIn, ResetRequestIn  # noqa: E402
from app.services import mailer as mailer_mod  # noqa: E402
from app.services.mailer import (  # noqa: E402
    DisabledSms,
    Mailer,
    MailerError,
    SmsNotConfigured,
    sms_provider_for,
)
from app.services.recovery import (  # noqa: E402
    CODE_DIGITS,
    code_hmac,
    compose_email,
    new_code,
    normalize_code,
)

EMAIL = "sana@example.com"
STRONG = "a-long-and-varied-passphrase-42"


def run(coro):
    return asyncio.run(coro)


# =============================================================================================== codes
def test_code_is_eight_digits_from_a_secure_source(monkeypatch):
    codes = {new_code() for _ in range(300)}
    assert all(re.fullmatch(r"[0-9]{8}", c) for c in codes)
    assert len(codes) > 290                      # not a constant or a tiny space
    seen = []
    monkeypatch.setattr("app.services.recovery.secrets.choice", lambda alphabet: seen.append(alphabet) or "7")
    assert new_code() == "7" * CODE_DIGITS and seen   # drawn with the `secrets` module


@pytest.mark.parametrize("raw,expected", [("1234 5678", "12345678"), ("1234-5678", "12345678"), (" 12345678 ", "12345678"),
                                          ("1234567", None), ("123456789", None), ("1234abcd", None), ("", None),
                                          ("１２３４５６７８", None)])  # full-width digits are not accepted
def test_normalize_code(raw, expected):
    assert normalize_code(raw) == expected


def test_code_hmac_is_keyed_bound_to_email_and_does_not_contain_the_code(crypto):
    h = code_hmac(crypto, EMAIL, "12345678")
    assert len(h) == 32 and h == code_hmac(crypto, EMAIL, "12345678")
    assert h != code_hmac(crypto, EMAIL, "12345679")
    assert h != code_hmac(crypto, "other@example.com", "12345678")           # a code cannot be replayed against another account
    assert b"12345678" not in h
    assert h != crypto.sign("something-else", f"{EMAIL}\x00".encode() + b"12345678")   # purpose separation


def test_email_text_has_code_expiry_and_no_secrets():
    subject, body = compose_email("12345678", 900, "https://sadqah.example/", by_staff=False)
    assert "1234 5678" in body and "15 minutes" in body and "https://sadqah.example/forgot-password" in body
    assert "password reset" in subject.lower()
    _, staff_body = compose_email("12345678", 900, "https://x", by_staff=True)
    assert "staff member started" in staff_body and "will never ask you" in staff_body


# =============================================================================================== SMTP
class FakeSMTP:
    instances: list = []

    def __init__(self, fail=None):
        self.fail, self.log, self.sent = fail, [], []
        FakeSMTP.instances.append(self)

    def ehlo(self): self.log.append("ehlo")
    def starttls(self, context=None): self.log.append("starttls")
    def login(self, user, password): self.log.append(("login", user))
    def quit(self): self.log.append("quit")

    def send_message(self, msg):
        if self.fail:
            raise self.fail
        self.sent.append(msg)


def settings(**kw):
    base = dict(env="dev", smtp_host="smtp.test", smtp_port=587, smtp_from="SadQah <no-reply@sadqah.test>",
                smtp_security="starttls", smtp_username="mailer", smtp_password="s3cret-smtp-pass")
    base.update(kw)
    return Settings(**base)


def make_mailer(fail=None, **kw):
    FakeSMTP.instances.clear()
    return Mailer(settings(**kw), lambda security, host, port, timeout: FakeSMTP(fail))


def test_smtp_success_uses_starttls_before_login_and_sets_headers():
    m = make_mailer()
    run(m.send(EMAIL, "Subject", "Body with 1234 5678"))
    c = FakeSMTP.instances[0]
    assert c.log[:4] == ["ehlo", "starttls", "ehlo", ("login", "mailer")] and c.log[-1] == "quit"
    msg = c.sent[0]
    assert msg["To"] == EMAIL and msg["From"].endswith("<no-reply@sadqah.test>") and msg["Auto-Submitted"] == "auto-generated"
    assert "1234 5678" in msg.get_content()


def test_smtp_ssl_mode_skips_starttls_and_no_login_without_username():
    m = make_mailer(smtp_security="ssl", smtp_username=None)
    run(m.send(EMAIL, "S", "B"))
    assert "starttls" not in FakeSMTP.instances[0].log and not any(isinstance(x, tuple) for x in FakeSMTP.instances[0].log)


def test_unconfigured_mailer_refuses_instead_of_pretending():
    m = Mailer(Settings(env="dev"), lambda *a: pytest.fail("must not connect"))
    assert m.available is False
    with pytest.raises(MailerError):
        run(m.send(EMAIL, "S", "B"))


@pytest.mark.parametrize("failure", [OSError("connection refused"), TimeoutError("slow"), smtplib.SMTPAuthenticationError(535, b"bad login for sana@example.com"),
                                     smtplib.SMTPRecipientsRefused({EMAIL: (550, b"no such user")})])
def test_smtp_failures_become_mailer_error_without_leaking_details(failure):
    m = make_mailer(fail=failure)
    with pytest.raises(MailerError) as info:
        run(m.send(EMAIL, "S", "B"))
    text = str(info.value)
    assert EMAIL not in text and "s3cret-smtp-pass" not in text and type(failure).__name__ in text
    assert FakeSMTP.instances[0].log[-1] == "quit"          # the connection is closed even when sending fails


def test_header_injection_is_refused():
    m = make_mailer()
    with pytest.raises(MailerError):
        run(m.send("a@b.com\r\nBcc: attacker@evil.com", "S", "B"))
    with pytest.raises(MailerError):
        run(m.send(EMAIL, "Hi\r\nBcc: attacker@evil.com", "B"))
    assert not FakeSMTP.instances or not FakeSMTP.instances[0].sent


def test_prod_refuses_clear_text_smtp():
    with pytest.raises(ValueError, match="SMTP_SECURITY"):
        Settings(env="prod", smtp_host="smtp.test", smtp_security="none", encryption_keys="v1:" + "A" * 43 + "=", blind_index_key="B" * 43 + "=",
                 token_pepper="C" * 43 + "=", jwt_secret="x" * 40, redis_url="redis://x", paypal_env="live", paypal_client_id="a",
                 paypal_client_secret="b", paypal_webhook_id="c")


# =============================================================================================== SMS stays off
def test_sms_is_disabled_by_default_and_never_claims_success():
    p = sms_provider_for(Settings(env="dev"))
    assert isinstance(p, DisabledSms) and p.available is False
    with pytest.raises(SmsNotConfigured):
        run(p.send("+923001234567", "hi"))
    assert isinstance(sms_provider_for(Settings(env="dev", sms_provider="acme")), DisabledSms)   # unknown name: still off


# =============================================================================================== route harness
class FakeConn:
    def __init__(self, db, role, user):
        self.db, self.role, self.user = db, role, user

    async def fetchrow(self, sql, *args):
        self.db.calls.append((self.role, self.user, sql, args))
        if "fn_pr_start" in sql:
            return self.db.start_row
        if "fn_admin_start_reset" in sql:
            if self.db.admin_error:
                raise self.db.admin_error
            return self.db.admin_row
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        self.db.calls.append((self.role, self.user, sql, args))
        if "fn_pr_redeem" in sql:
            return self.db.redeem_result
        return None


class FakeDB:
    def __init__(self):
        self.calls, self.start_row, self.admin_row, self.admin_error, self.redeem_result = [], None, None, None, False

    @contextlib.asynccontextmanager
    async def session(self, role, user_id=None):
        yield FakeConn(self, role, user_id)

    def api(self, user_id=None):
        return self.session("api", user_id)

    def named(self, fragment):
        return [c for c in self.calls if fragment in c[2]]


@pytest.fixture()
def env(crypto, monkeypatch):
    monkeypatch.setattr(deps.Request, "__init__", lambda self, *a, **k: None, raising=False)
    db = FakeDB()
    s = settings()
    st = AppState(settings=s, db=db, crypto=crypto, vault=None, paypal=None, limiter=RateLimiter(None))
    FakeSMTP.instances.clear()
    monkeypatch.setattr(routes, "_mailer", Mailer(s, lambda security, host, port, timeout: FakeSMTP(getattr(db, "smtp_fail", None))))
    monkeypatch.setattr(routes, "hash_password", lambda p: "$argon2id$fake$" + p[::-1])
    user_row = {"reset_id": uuid.uuid4(), "email_ct": crypto.encrypt_text(EMAIL, aad.USER_EMAIL), "phone_ct": None}
    return types.SimpleNamespace(st=st, db=db, crypto=crypto, user_row=user_row, settings=s)


def request(env, email=EMAIL, channel="email"):
    bt = routes.BackgroundTasks()
    out = run(routes.request_reset(ResetRequestIn(email=email, channel=channel), bt, env.st))
    return out, bt


# =============================================================================================== route: request
def test_request_answer_is_identical_for_known_and_unknown_accounts(env):
    env.db.start_row = env.user_row
    known, bt_known = request(env)
    env.db.start_row = None
    unknown, bt_unknown = request(env, email="nobody@example.com")
    malformed, bt_bad = request(env, email="not-an-email")
    assert known == unknown == malformed
    assert len(bt_known.tasks) == 1 and not bt_unknown.tasks and not bt_bad.tasks
    assert FakeSMTP.instances == []                       # nothing is sent while the response is being built


def test_background_tasks_are_the_frameworks_own_class_and_hold_the_delivery_job(env):
    # Written against Starlette's BackgroundTasks (what FastAPI re-exports), so it passes the same way with the real FastAPI
    # installed and with the stand-in in tests/_fastapi_stub.py, which now re-uses that very class instead of a look-alike.
    from starlette.background import BackgroundTask, BackgroundTasks

    env.db.start_row = env.user_row
    _, bt = request(env)
    assert isinstance(bt, BackgroundTasks) and len(bt.tasks) == 1
    (task,) = bt.tasks
    assert isinstance(task, BackgroundTask) and task.func is routes._deliver
    assert FakeSMTP.instances == []                       # queued, not yet run
    run(bt())
    assert len(FakeSMTP.instances) == 1                   # running the queue is what sends


def test_public_confirmation_does_not_claim_delivery_before_the_mail_task_has_run(env):
    env.db.start_row = env.user_row
    out, bt = request(env)
    text = out.message.lower()
    assert FakeSMTP.instances == []                       # at this moment nothing has been sent
    assert "will be sent" in text and "shortly" in text
    for claim in ("have sent", "has been sent", "we sent", "was sent", "been delivered", "is on its way", "check your inbox"):
        assert claim not in text, claim
    assert out.message == routes.ACCEPTED


def test_admin_request_body_cannot_name_the_administrator():
    # the administrator is always the signed-in session, never a field the caller supplies
    assert set(AdminResetIn.model_fields) == {"email"}


def test_code_is_emailed_after_the_response_and_only_its_hmac_reaches_the_database(env):
    env.db.start_row = env.user_row
    _, bt = request(env)
    run(bt())
    msg = FakeSMTP.instances[0].sent[0]
    code = normalize_code(re.search(r"code: (\d{4} \d{4})", msg.get_content()).group(1))
    assert msg["To"] == EMAIL
    (_, _, sql, args), = env.db.named("fn_pr_start")
    assert args[1] == code_hmac(env.crypto, EMAIL, code) and code.encode() not in args[1]
    assert code not in repr(args) and args[2] == env.settings.recovery_code_ttl_seconds and args[3] == "email"


def test_request_with_email_not_configured_is_an_honest_503_not_a_fake_success(env, monkeypatch):
    monkeypatch.setattr(routes, "_mailer", Mailer(Settings(env="dev"), lambda *a: pytest.fail("no connection")))
    with pytest.raises(errors.ApiError) as e:
        request(env)
    assert e.value.status == 503 and not env.db.calls


def test_sms_request_is_refused_while_no_provider_exists(env):
    with pytest.raises(errors.ApiError) as e:
        request(env, channel="sms")
    assert e.value.status == 400 and e.value.code == "channel_unavailable" and not env.db.calls


def test_options_report_what_is_really_deliverable(env, monkeypatch):
    assert run(routes.options(env.st)).model_dump() == {"email": True, "sms": False}
    monkeypatch.setattr(routes, "_mailer", Mailer(Settings(env="dev"), None))
    assert run(routes.options(env.st)).model_dump() == {"email": False, "sms": False}


def test_per_email_rate_limit_counts_unknown_accounts_too(env):
    env.db.start_row = None                               # nobody has this e-mail
    for _ in range(3):
        request(env, email="ghost@example.com")
    with pytest.raises(errors.ApiError) as e:
        request(env, email="ghost@example.com")
    assert e.value.status == 429
    env.db.start_row = env.user_row                       # ...and a real account is limited in exactly the same way
    for _ in range(3):
        request(env, email="real@example.com")
    with pytest.raises(errors.ApiError) as e2:
        request(env, email="real@example.com")
    assert e2.value.status == 429 and e2.value.message == e.value.message


def test_per_address_rate_limit_dependency():
    st = types.SimpleNamespace(settings=types.SimpleNamespace(trusted_proxy_count=0), limiter=RateLimiter(None),
                               crypto=None)
    # the dependency hashes the caller address with a peppered key: use the real crypto from the fixture-less path
    from app.core.crypto import Crypto
    st.crypto = Crypto({"k": bytes(range(32))}, "k", b"b" * 32, b"p" * 32)
    req = types.SimpleNamespace(client=types.SimpleNamespace(host="203.0.113.9"), headers={})
    dep = routes._REQUEST_IP_LIMIT
    for _ in range(10):
        run(dep(req, st))
    with pytest.raises(errors.ApiError) as e:
        run(dep(req, st))
    assert e.value.status == 429 and e.value.headers["Retry-After"]


def test_failed_delivery_closes_the_code_and_logs_no_address(env, caplog):
    env.db.start_row = env.user_row
    env.db.smtp_fail = smtplib.SMTPRecipientsRefused({EMAIL: (550, b"nope")})
    out, bt = request(env)                                # the HTTP answer is unchanged by a delivery problem
    assert "If an account" in out.message
    with caplog.at_level(logging.DEBUG):
        run(bt())
    (call,) = env.db.named("fn_pr_delivery_failed")
    assert call[0] == "api" and call[3][0] == env.user_row["reset_id"] and call[3][1] == "MailerError"
    assert EMAIL not in caplog.text and "s3cret-smtp-pass" not in caplog.text


# =============================================================================================== route: confirm
def confirm(env, **over):
    body = dict(email=EMAIL, code="1234 5678", new_password=STRONG)
    body.update(over)
    return run(routes.confirm_reset(ResetConfirmIn(**body), env.st))


def test_confirm_failures_are_one_indistinguishable_answer(env):
    env.db.redeem_result = False
    cases = [dict(), dict(email="nobody@example.com"), dict(code="00000000"), dict(code="12"), dict(email="bad")]
    seen = set()
    for over in cases:
        with pytest.raises(errors.ApiError) as e:
            confirm(env, **over)
        seen.add((e.value.status, e.value.code, e.value.message))
    assert seen == {(400, "invalid_code", routes.BAD_CODE)}


def test_confirm_success_hashes_the_new_password_and_never_stores_plaintext(env):
    env.db.redeem_result = True
    assert confirm(env).status_code == 204
    (_, _, sql, args), = env.db.named("fn_pr_redeem")
    assert args[0] == env.crypto.blind_index("email", EMAIL) and args[1] == code_hmac(env.crypto, EMAIL, "12345678")
    assert args[2].startswith("$argon2id$") and STRONG not in repr(args)


def test_confirm_does_the_same_hashing_work_for_unknown_accounts(env):
    hashed = []
    routes.hash_password = lambda p: hashed.append(p) or "$argon2id$fake$x"
    env.db.redeem_result = False
    for over in (dict(), dict(email="nobody@example.com")):
        with pytest.raises(errors.ApiError):
            confirm(env, **over)
    assert hashed == [STRONG, STRONG]


def test_confirm_enforces_the_password_policy_before_anything_else(env):
    with pytest.raises(errors.ApiError) as e:
        confirm(env, new_password="short")
    assert e.value.status == 422 and "new_password" in e.value.fields and not env.db.calls


def test_confirm_attempts_are_rate_limited_per_email(env):
    env.db.redeem_result = False
    for _ in range(10):
        with pytest.raises(errors.ApiError) as e:
            confirm(env)
        assert e.value.status == 400
    with pytest.raises(errors.ApiError) as e:
        confirm(env)
    assert e.value.status == 429


# =============================================================================================== route: admin
def admin_call(env, admin_id=None, email=EMAIL):
    bt = routes.BackgroundTasks()
    session = Session(admin_id or uuid.uuid4(), "admin", "csrf", 9999999999)
    return run(routes.admin_start_reset(AdminResetIn(email=email), bt, session, env.st)), bt, session


def test_only_admins_pass_the_route_dependency():
    dep = inspect.signature(routes.admin_start_reset).parameters["session"].default.dependency
    assert dep is deps.require_admin
    check = deps.require_admin.__wrapped__ if hasattr(deps.require_admin, "__wrapped__") else deps.require_admin
    for role in ("donor", "recipient", "reviewer"):
        with pytest.raises(errors.ApiError) as e:
            check(Session(uuid.uuid4(), role, "c", 9999999999))
        assert e.value.status == 403
    admin = Session(uuid.uuid4(), "admin", "c", 9999999999)
    assert check(admin) is admin


def test_admin_start_runs_on_the_admin_role_and_never_returns_the_code(env):
    env.db.admin_row = {"outcome": "created", "reset_id": uuid.uuid4(), "email_ct": env.user_row["email_ct"]}
    out, bt, session = admin_call(env)
    run(bt())
    (role, user, sql, args), = env.db.named("fn_admin_start_reset")
    assert role == "admin" and user == session.user_id and args[0] == session.user_id
    msg = FakeSMTP.instances[0].sent[0]
    assert msg["To"] == EMAIL and "staff member started" in msg.get_content()
    sent_code = normalize_code(re.search(r"code: (\d{4} \d{4})", msg.get_content()).group(1))
    assert args[2] == code_hmac(env.crypto, EMAIL, sent_code)
    shown = out.model_dump_json()
    assert out.status == "code_sent" and sent_code not in shown and EMAIL not in shown and not re.search(r"\d{8}", shown)


def test_admin_start_opens_its_database_session_as_the_same_user_it_names(env):
    # core.fn_admin_start_reset refuses unless p_admin equals the session's user id, so the route must pass one id to both
    env.db.admin_row = {"outcome": "no_eligible_account", "reset_id": None, "email_ct": None}
    admin_id = uuid.uuid4()
    _, _, session = admin_call(env, admin_id=admin_id)
    (role, user, sql, args), = env.db.named("fn_admin_start_reset")
    assert role == "admin" and user == admin_id == session.user_id and args[0] == admin_id


@pytest.mark.parametrize("outcome", ["no_eligible_account", "too_soon"])
def test_admin_start_reports_refusals_without_sending(env, outcome):
    env.db.admin_row = {"outcome": outcome, "reset_id": None, "email_ct": None}
    out, bt, _ = admin_call(env)
    run(bt())
    assert out.status == outcome and FakeSMTP.instances == []


def test_admin_start_database_refusal_is_a_403(env):
    class InsufficientPrivilegeError(Exception):
        pass
    routes.asyncpg.InsufficientPrivilegeError = InsufficientPrivilegeError   # the real class when asyncpg is installed
    env.db.admin_error = routes.asyncpg.InsufficientPrivilegeError("only an active administrator")
    with pytest.raises(errors.ApiError) as e:
        admin_call(env)
    assert e.value.status == 403


def test_admin_start_with_no_email_configured_is_honest(env, monkeypatch):
    monkeypatch.setattr(routes, "_mailer", Mailer(Settings(env="dev"), None))
    with pytest.raises(errors.ApiError) as e:
        admin_call(env)
    assert e.value.status == 503 and not env.db.calls


def test_admin_delivery_failure_is_recorded_on_the_admin_role(env):
    env.db.smtp_fail = OSError("network down")
    rid = uuid.uuid4()
    env.db.admin_row = {"outcome": "created", "reset_id": rid, "email_ct": env.user_row["email_ct"]}
    _, bt, _ = admin_call(env)
    run(bt())
    (call,) = env.db.named("fn_pr_delivery_failed")
    assert call[0] == "admin" and "core.fn_pr_delivery_failed" in call[2] and call[3][0] == rid


# =============================================================================================== SMS interface plumbing
def test_a_registered_sms_provider_is_used_and_its_failure_closes_the_code(env, monkeypatch):
    sent = []

    class Fake:
        name, available = "fake", True

        async def send(self, phone, text):
            sent.append((phone, text))

    s = settings(sms_provider="fake")
    monkeypatch.setitem(mailer_mod.SMS_PROVIDERS, "fake", lambda _s: Fake())
    env.st.settings = s
    phone_ct = env.crypto.encrypt_text("+923001234567", aad.USER_PHONE)
    env.db.start_row = {**env.user_row, "phone_ct": phone_ct}
    _, bt = request(env, channel="sms")
    run(bt())
    assert sent and sent[0][0] == "+923001234567" and re.search(r"\d{4} \d{4}", sent[0][1])

    class Broken(Fake):
        async def send(self, phone, text):
            raise SmsNotConfigured("down")

    monkeypatch.setitem(mailer_mod.SMS_PROVIDERS, "fake", lambda _s: Broken())
    _, bt2 = request(env, channel="sms", email="other@example.com")
    run(bt2())
    assert env.db.named("fn_pr_delivery_failed")
