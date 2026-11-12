"""Turns what the vision model read from income documents into one monthly USD figure and the "< $50" verdict.

The model only EXTRACTS numbers. The arithmetic and the threshold live here, in plain code a reviewer can read.
When documents disagree we keep the HIGHEST plausible estimate: it is the safe direction for a charity that
wants to help people who are genuinely below the line.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncomeEstimate:
    monthly_usd_cents: int | None
    currency: str | None = None
    basis: str = "unknown"
    flags: list[dict[str, str]] = field(default_factory=list)


def to_usd_cents(amount_local: float, currency: str, fx_rates: dict[str, float]) -> int | None:
    rate = fx_rates.get(currency.upper())
    if rate is None or amount_local < 0:
        return None
    return int(round(amount_local * rate * 100))


def _monthly_local(extraction: dict[str, Any]) -> tuple[float, str] | None:
    stated = extraction.get("stated_monthly_income")
    if isinstance(stated, (int, float)) and stated >= 0:
        return float(stated), "stated monthly income"
    credits, months = extraction.get("total_credits"), extraction.get("months_covered")
    if isinstance(credits, (int, float)) and isinstance(months, (int, float)) and credits >= 0 and months > 0:
        return float(credits) / float(months), f"average of credits over {months:g} months"
    return None


def estimate_monthly_income(extractions: list[dict[str, Any]], fx_rates: dict[str, float],
                            threshold_cents: int) -> IncomeEstimate:
    best: tuple[int, str, str] | None = None
    flags: list[dict[str, str]] = []
    for ex in extractions:
        monthly = _monthly_local(ex)
        currency = str(ex.get("currency") or "").upper()
        if monthly is None:
            continue
        if not currency or currency not in fx_rates:
            flags.append({"code": "unknown_currency", "severity": "warning",
                          "detail": f"Income document uses currency '{currency or 'unspecified'}' with no exchange rate configured."})
            continue
        usd = to_usd_cents(monthly[0], currency, fx_rates)
        if usd is not None and (best is None or usd > best[0]):
            best = (usd, currency, monthly[1])

    if best is None:
        flags.append({"code": "income_unreadable", "severity": "critical",
                      "detail": "No monthly income could be determined from the documents. A reviewer must read them."})
        return IncomeEstimate(None, None, "unknown", flags)

    usd, currency, basis = best
    if usd >= threshold_cents:
        flags.append({"code": "income_above_threshold", "severity": "critical",
                      "detail": f"Estimated income of about ${usd / 100:.2f} a month is not below the ${threshold_cents / 100:.0f} limit."})
    return IncomeEstimate(usd, currency, basis, flags)
