import pytest
from pydantic import ValidationError

from app.schemas.donations import CreateOrderIn, PledgeIn


def test_order_amount_must_be_int():
    ok = CreateOrderIn(campaign_slug="a-b", amount_cents=500, is_anonymous=True)
    assert ok.amount_cents == 500
    for bad in (5.5, "500", True):
        with pytest.raises(ValidationError):
            CreateOrderIn(campaign_slug="a-b", amount_cents=bad, is_anonymous=False)
    with pytest.raises(ValidationError):
        CreateOrderIn(campaign_slug="A B", amount_cents=500, is_anonymous=False)
    with pytest.raises(ValidationError):
        CreateOrderIn(campaign_slug="a", amount_cents=500, is_anonymous=False, extra=1)


def test_pledge_rules():
    PledgeIn(kind="percent_of_income", percent=2.5, amount_cents=1000, frequency="monthly")
    PledgeIn(kind="fixed_amount", amount_cents=1000, frequency="yearly")
    for kw in (dict(kind="percent_of_income", percent=None), dict(kind="percent_of_income", percent=2.3),
               dict(kind="percent_of_income", percent=6), dict(kind="fixed_amount", percent=2)):
        with pytest.raises(ValidationError):
            PledgeIn(amount_cents=1000, frequency="monthly", **kw)
