"""Contact Us feature: the real /contact page, its links, and what the assistant says about it.

Unit and source-level tests (no browser, no live model). The rendered behaviour (mailto link, copy button, keyboard, layout) was
checked separately in a headless browser harness; see docs/CONTACT_US.md for what was and was not verified.
"""

import re
from pathlib import Path

import pytest

from tests import _fastapi_stub
from tests import test_assistant_history_and_limits as shared
from tests.test_assistant_ollama import chat_reply

_fastapi_stub.install()

# fixtures and helpers shared with the other assistant tests (the fake Ollama server, an AppState factory)
make, ollama, request, run = shared.make, shared.ollama, shared.request, shared.run

from app.api.routes import assistant as routes  # noqa: E402
from app.services import assistant as svc  # noqa: E402
from app.services.assistant import (  # noqa: E402
    GUIDE_SYSTEM,
    SITE_GUIDE,
    UNSUPPORTED_ANSWER,
    faq_answer,
    unsupported_answer,
)

EMAIL = "sadqahsupport@gmail.com"
SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
needs_frontend = pytest.mark.skipif(not SRC.is_dir(), reason="frontend sources are not part of this checkout / image")

CONTACT_QUESTIONS = [
    "How can I contact SadQah?", "I want to get in touch with support", "what is your support email", "How do I reach support?",
    "Is there a support team?", "contact", "Where is the contact page?",
]


def emails_in(text: str) -> set[str]:
    return set(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+[\w]", text))


# ------------------------------------------------------------------------------------------ assistant knowledge
def test_guide_names_the_real_contact_page_and_exact_address():
    assert "/contact" in SITE_GUIDE and EMAIL in SITE_GUIDE and "Contact us" in SITE_GUIDE
    assert emails_in(SITE_GUIDE) == {EMAIL} and emails_in(GUIDE_SYSTEM) == {EMAIL}


def test_guide_no_longer_claims_there_is_no_contact_channel():
    for text in (SITE_GUIDE, GUIDE_SYSTEM, UNSUPPORTED_ANSWER, faq_answer("hello there"), faq_answer("hello", ai_failed=True)):
        low = text.lower()
        assert "no support phone number, e-mail address" not in low
        assert "without giving a channel" not in low
        assert "as if a contact method exists" not in low
        assert "shows no support" not in low
    # what is genuinely absent is still stated honestly
    assert "no live chat with staff, no support phone line and no contact form" in SITE_GUIDE


def test_system_prompt_sends_people_to_contact_page_without_promises_or_invented_details():
    p = GUIDE_SYSTEM
    assert "e-mail to sadqahsupport@gmail.com" in p and "(/contact)" in p
    for must in ("Never promise a reply time", "never say a message has been sent", "never invent any other contact detail",
                 "Never tell anyone to e-mail passwords, one-time codes, payment credentials or identity documents"):
        assert must in p, must
    assert "I am not sure about that" in p and "never say whether a payment happened" in p      # honesty rules kept


def test_guide_says_nothing_is_sent_until_the_visitor_presses_send_and_promises_no_reply_time():
    assert "nothing is sent until they press Send" in SITE_GUIDE and "No reply time is promised" in SITE_GUIDE
    for text in (SITE_GUIDE, svc.CONTACT_ANSWER):
        assert not re.search(r"within \d+|\d+ (hours|days)|business hours|24/7|we will (reply|respond)|we'll (reply|respond)", text, re.I)


def test_nothing_in_the_assistant_text_asks_for_secrets_by_email():
    for text in (SITE_GUIDE, GUIDE_SYSTEM, svc.CONTACT_ANSWER, UNSUPPORTED_ANSWER, faq_answer("I forgot my password")):
        assert not re.search(r"(send|e-?mail|write)\s+(us\s+|me\s+)?(your|the)\s+(password|code|card|id|passport)", text, re.I)
    assert "never e-mail passwords, one-time codes" in svc.CONTACT_ANSWER.lower()


@pytest.mark.parametrize("q", CONTACT_QUESTIONS)
def test_built_in_faq_answers_contact_questions_with_the_real_page_and_address(q):
    a = faq_answer(q)
    assert a == svc.CONTACT_ANSWER and EMAIL in a and "/contact" in a and emails_in(a) == {EMAIL}
    assert "no live chat" in a and "no reply time is promised" in a
    assert "sent" not in a.lower().replace("nothing is sent until you press send", "")      # never claims a message was sent


def test_other_faq_topics_are_not_hijacked_by_the_contact_entry():
    assert "Settings" in faq_answer("how do I delete my account") and "batches" in faq_answer("when will my payout arrive")
    assert "Donation Token" in faq_answer("how do I track an anonymous gift")


def test_password_faq_points_to_email_and_contact_page_and_still_protects_the_code():
    a = faq_answer("I forgot my password")
    assert "Forgot your password?" in a and EMAIL in a and "/contact" in a and "never include your password or a code" in a
    assert "no self-service reset" not in a


def test_fallbacks_mention_the_contact_route_without_hiding_that_the_ai_is_limited():
    off, failed = faq_answer("zzz qqq"), faq_answer("zzz qqq", ai_failed=True)
    for a in (off, failed):
        assert EMAIL in a and "/contact" in a
    assert "not switched on" in off and "could not answer just now" in failed


def test_unsupported_answer_gives_the_one_real_channel_and_is_still_honest():
    low = UNSUPPORTED_ANSWER.lower()
    assert EMAIL in UNSUPPORTED_ANSWER and "/contact" in UNSUPPORTED_ANSWER
    assert "can't confirm" in low and "won't guess" in low and "no live chat" in low and "no support phone line" in low
    assert emails_in(UNSUPPORTED_ANSWER) == {EMAIL} and "no reply time is promised" in low
    assert unsupported_answer("what is your phone number") == UNSUPPORTED_ANSWER


def test_route_with_a_working_model_puts_the_contact_facts_in_the_system_prompt(make, ollama):
    st = make()
    ollama.reply = chat_reply("E-mail sadqahsupport@gmail.com; see /contact.")
    out = run(routes.chat(request([("user", "How can I contact you?")]), None, st))
    assert out.ai is True
    system = ollama.requests[-1]["body"]["messages"][0]
    assert system["role"] == "system" and EMAIL in system["content"] and "/contact" in system["content"]
    assert "Never promise a reply time" in system["content"]


def test_route_when_the_model_is_down_still_gives_the_real_contact_answer(make, ollama):
    st = make()
    ollama.reply = lambda body: (500, {"error": "boom"}, {})
    out = run(routes.chat(request([("user", "how do I contact support?")]), None, st))
    assert out.ai is False and out.reply == svc.CONTACT_ANSWER


def test_a_phone_question_never_reaches_the_model_and_names_the_email_instead(make, ollama):
    st = make()
    out = run(routes.chat(request([("user", "What is your phone number?")]), None, st))
    assert out.ai is False and EMAIL in out.reply and ollama.requests == []


def test_previous_assistant_fixes_are_still_present():
    for name in ("normalize_history", "unsupported_answer", "faq_answer", "AssistantBusy", "OllamaError", "AssistantUnavailable", "_ollama_post", "NOT_CHECKED"):
        assert hasattr(svc, name), name
    from app.core.config import Settings
    for field in ("ollama_max_concurrent", "ollama_max_queue", "assistant_history_messages", "assistant_history_chars", "ollama_timeout_seconds", "ollama_num_ctx", "ollama_max_tokens"):
        assert field in Settings.model_fields, field


# ------------------------------------------------------------------------------------------ frontend sources
def read(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


@needs_frontend
def test_shared_constants_match_the_assistant_guide():
    c = read("lib/contact.ts")
    assert re.search(r'SUPPORT_EMAIL = "([^"]+)"', c).group(1) == EMAIL
    assert 'SUPPORT_SUBJECT = "SadQah Support Request"' in c
    assert "mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(SUPPORT_SUBJECT)}" in c
    assert emails_in(c) == {EMAIL}


@needs_frontend
def test_contact_route_exists_as_a_server_page_with_metadata_and_content():
    assert (SRC / "app" / "contact" / "page.tsx").is_file()
    p = read("app/contact/page.tsx")
    assert "export const metadata" in p and 'title: "Contact us"' in p and "export default function ContactPage" in p
    assert not p.lstrip().startswith('"use client"')                                                  # renders on the server: direct load and refresh work
    assert "<h1" in p and ">Contact us</h1>" in p and "{SUPPORT_EMAIL}" in p and "href={SUPPORT_MAILTO}" in p and "Write an email" in p
    assert "<CopyEmail />" in p
    for needle in ("password", "one-time code", "identity documents", "Card numbers", "will never ask you", "We cannot promise how quickly"):
        assert needle in p, needle
    assert emails_in(p) == set()                                                                      # the address comes only from lib/contact.ts


@needs_frontend
def test_contact_page_invents_no_other_channels_hours_or_places():
    p = read("app/contact/page.tsx")
    assert "<form" not in p and "<textarea" not in p and "tel:" not in p and "whatsapp" not in p.lower()
    assert not re.search(r"\b(\d{2,}[- ]\d{3,}|business hours|office hours|24/7|within \d+|working days)\b", p, re.I)
    assert "no phone line, live chat or contact form" in p and "cannot send messages for you" in p


@needs_frontend
def test_copy_button_has_accessible_feedback_and_a_failure_path():
    c = read("components/contact/CopyEmail.tsx")
    assert c.lstrip().startswith('"use client"')
    assert 'role="status"' in c and 'aria-live="polite"' in c                                          # announced by screen readers
    assert "navigator.clipboard.writeText(SUPPORT_EMAIL)" in c and "catch" in c
    assert "Copy email address" in c and "Copied" in c and "Could not copy automatically" in c
    assert "clearTimeout" in c                                                                         # no timer leak on unmount


@needs_frontend
def test_footer_links_to_contact_exactly_once_for_everyone():
    f = read("components/layout/Footer.tsx")
    assert len(re.findall(r'href="/contact"', f)) == 1 and "Contact us" in f
    assert "useAuth" not in f                                                                          # not hidden behind sign-in state
    assert "/contact" not in read("components/layout/Header.tsx")                                      # nav not duplicated


@needs_frontend
def test_pages_that_say_contact_support_now_link_to_the_contact_page():
    for rel in ("app/settings/page.tsx", "app/trust/page.tsx", "app/forgot-password/page.tsx", "app/recipient/profile/page.tsx"):
        assert 'href="/contact"' in read(rel), rel


@needs_frontend
def test_widget_turns_contact_mentions_into_links():
    assert re.search(r'const PAGES = \[[^\]]*"/contact"', read("components/assistant/AssistantWidget.tsx"), re.S)


@needs_frontend
def test_no_frontend_text_still_claims_there_is_no_contact_channel():
    bad = re.compile(r"no support (phone|e-?mail)|without giving a channel|no (way|channel) to contact|cannot be contacted|no contact (page|form|channel)", re.I)
    for f in SRC.rglob("*.tsx"):
        t = f.read_text(encoding="utf-8")
        assert not bad.search(t), f


def test_docs_describe_the_contact_page_and_no_longer_say_no_channel_exists():
    docs = Path(__file__).resolve().parents[2] / "docs"
    if not docs.is_dir():
        pytest.skip("docs are not part of this checkout")
    d = (docs / "OLLAMA_ASSISTANT.md").read_text(encoding="utf-8")
    assert EMAIL in d and "/contact" in d
    assert "no support phone number or e-mail address" not in d and "without giving a channel" not in d
    assert EMAIL in (docs / "CONTACT_US.md").read_text(encoding="utf-8")
