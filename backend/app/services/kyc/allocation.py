"""The "Exit Poverty" micro-business capital recommendation.

Deliberately simple and explainable:

    gap      = target monthly income  -  verified monthly income         (what the business must add each month)
    capital  = gap x 4                                                    (about four months of the missing income)
    capital  = clamp(capital, minimum, maximum)
    capital  = at most gap x max_payback_months                           (extra income must be able to repay it)
    capital  = rounded to the nearest $5

The result is advisory. A human reviewer may change it, and the database refuses a campaign goal above the
approved figure.
"""
from __future__ import annotations


def recommend_allocation(monthly_income_cents: int | None, *, target_monthly_cents: int, min_cents: int,
                         max_cents: int, max_payback_months: int) -> int | None:
    if monthly_income_cents is None or monthly_income_cents < 0:
        return None
    gap = max(0, target_monthly_cents - monthly_income_cents)
    capital = max(min_cents, min(max_cents, gap * 4))
    capital = min(capital, max(min_cents, gap * max_payback_months))
    return int(round(capital / 500.0)) * 500
