import pytest

from app.services.moderation import screen_text


@pytest.mark.parametrize("text", [
    "Wishing you and your family every blessing.",
    "I hope the new oven works out beautifully!",
    "God bless your shop, keep going.",
])
def test_kind_messages_pass(text):
    assert screen_text(text).allowed


@pytest.mark.parametrize("text", [
    "email me at a@b.com",
    "visit https://example.com",
    "call 0300 1234567",
    "zero three zero zero one two three four five six",
    "",
    "x" * 1001,
])
def test_contact_details_and_bounds_blocked(text):
    v = screen_text(text)
    assert not v.allowed and v.reason
