"""Pure-logic tests for the assistant: arithmetic flags, tamper-proof coercion of model output, FAQ fallback, schemas."""
import pytest
from pydantic import ValidationError

from app.schemas.account import DeleteAccountRequest
from app.schemas.assistant import ChatRequest, NeedItemIn, NeedsIn
from app.services.assistant import (
    AskedItem,
    coerce_estimates,
    coerce_proof,
    evaluate_items,
    faq_answer,
    route_priority,
    summarize,
)

EST = {0: {"category": "sewing", "unit": "machine", "low": 18000.0, "typical": 25000.0, "high": 32000.0, "confidence": 0.8,
           "plausible": True, "luxury": False, "note": "new manual machine"}}


def one(price, qty=1.0, est=EST):
    return evaluate_items([AskedItem("Sewing machine", qty, price)], est)[0]


def test_price_bands():
    assert one(25000).status == "ok"
    assert one(34000).status == "ok"                 # up to 15% over the high end is tolerated
    assert one(40000).status == "high"
    assert one(90000).status == "very_high"
    assert one(1000).status == "low"
    assert one(90000).recommended_unit_price == 32000.0   # suggested amount is capped at the market high
    assert one(25000).recommended_unit_price == 25000.0


def test_unknown_when_no_or_weak_estimate():
    assert one(100, est={}).status == "unknown"
    weak = {0: {**EST[0], "confidence": 0.1}}
    r = one(100, est=weak)
    assert r.status == "unknown" and "no_reliable_estimate" in r.flags


def test_flags_unrelated_luxury_and_quantity():
    est = {0: {**EST[0], "plausible": False, "luxury": True}}
    r = one(25000, qty=25, est=est)
    assert {"unrelated_to_business", "personal_or_luxury", "large_quantity"} <= set(r.flags)


def test_summary_caps_at_allocation_and_flags():
    results = [one(90000)]
    s = summarize(results, usd_per_local=0.0036, allocation_cents=10000)
    assert "some_prices_far_above_market" in s["flags"] and "exceeds_approved_allocation" in s["flags"]
    assert s["asked_total_usd_cents"] == 32400
    assert s["suggested_total_usd_cents"] == 11520
    assert s["suggested_goal_usd_cents"] == 10000      # never above what the reviewer approved
    assert route_priority("LOW", s, results) == "HIGH"  # arithmetic can raise the queue priority, never lower it


def test_summary_without_exchange_rate_has_no_dollar_values():
    s = summarize([one(25000)], usd_per_local=None, allocation_cents=10000)
    assert s["asked_total_usd_cents"] is None and s["suggested_goal_usd_cents"] is None


def test_priority_never_lowered():
    results = [one(25000)]
    s = summarize(results, 0.0036, None)
    assert route_priority("HIGH", s, results) == "HIGH"
    assert route_priority("LOW", s, results) == "LOW"


def test_coerce_estimates_survives_garbage():
    raw = {"usd_per_local": "abc", "items": [
        {"index": True, "low": 1, "typical": 2, "high": 3},                 # bool is not an index
        {"index": 5, "low": 1, "typical": 2, "high": 3},                    # out of range
        {"index": 0, "low": float("nan"), "typical": 2, "high": 3},         # NaN rejected, typical+high insufficient
        {"index": 1, "low": 9, "typical": 5, "high": 1, "confidence": 7, "note": "x" * 999},   # unsorted, absurd confidence
        "not a dict"]}
    rate, out = coerce_estimates(raw, 2)
    assert rate is None
    assert set(out) == {1}
    assert (out[1]["low"], out[1]["typical"], out[1]["high"]) == (1, 5, 9)
    assert out[1]["confidence"] == 0.0 and len(out[1]["note"]) <= 200


def test_coerce_proof_forces_the_schema():
    r = coerce_proof({"hr_filter_status": "APPROVED!", "priority_queue": "urgent", "flags_found": "nope", "notes_for_human_reviewer": ""})
    assert r["hr_filter_status"] == "FLAGGED_SUSPICIOUS" and r["priority_queue"] == "MEDIUM"
    assert r["flags_found"] == ["None"] and r["notes_for_human_reviewer"]
    ok = coerce_proof({"hr_filter_status": "PASSED", "priority_queue": "LOW", "flags_found": ["a", "", 5], "notes_for_human_reviewer": "Clear."})
    assert ok["hr_filter_status"] == "PASSED" and ok["flags_found"] == ["a", "5"]


def test_faq_fallback():
    assert "Settings" in faq_answer("How do I delete my account?")
    assert "Donation Token" in faq_answer("I lost my anonymous token")
    assert "not switched on" in faq_answer("zzzz")


def test_schemas():
    assert DeleteAccountRequest(password="x", confirm="DELETE")
    with pytest.raises(ValidationError):
        DeleteAccountRequest(password="x", confirm="delete")
    with pytest.raises(ValidationError):
        NeedItemIn(name="a", quantity=0, asked_price=1)
    with pytest.raises(ValidationError):
        NeedsIn(currency="PKRS", items=[{"name": "ab", "quantity": 1, "asked_price": 1}])
    with pytest.raises(ValidationError):
        NeedsIn(currency="PKR", items=[])
    assert ChatRequest(messages=[{"role": "user", "content": "hi"}])
    with pytest.raises(ValidationError):
        ChatRequest(messages=[{"role": "system", "content": "hi"}])
