"""Deterministic financial health score.

This is the single source of truth for the score. The LLM must NEVER compute
this number, only narrate it.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any


def _to_decimal(val: Any) -> Decimal:
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    try:
        s = str(val).strip()
        return Decimal(s) if s else Decimal("0.00")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _round_money(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate_health_score(
    income: float,
    expenses: float,
    anomalies_count: int,
    emergency_fund_months: float,
    active_emis: int,
) -> tuple[int, float]:
    """Return (score, savings_rate). Exact formula from the spec using Decimal math."""
    inc = max(Decimal("0.00"), _to_decimal(income))
    exp = max(Decimal("0.00"), _to_decimal(expenses))
    savings_rate = (inc - exp) / inc if inc > Decimal("0.00") else Decimal("0.00")

    score = 100
    if savings_rate < Decimal("0.10"):
        score -= 30
    elif savings_rate < Decimal("0.20"):
        score -= 15

    anom_cnt = int(anomalies_count or 0)
    score -= min(anom_cnt * 10, 30)

    ef_months = _to_decimal(emergency_fund_months)
    if ef_months < Decimal("3.0"):
        score -= 20

    emis = int(active_emis or 0)
    score -= min(emis * 5, 15)

    final_score = max(0, min(100, score))
    return final_score, round(float(savings_rate), 4)


def build_health_score(
    monthly_summary: dict,
    anomalies: list[dict],
    emergency_fund_months: float = 0.0,
    active_emis: int = 0,
) -> dict:
    """Compute the score using the latest full month as the reference period."""
    months = monthly_summary.get("months", [])
    if not months:
        return {
            "score": 0,
            "savings_rate": 0.0,
            "income": 0.0,
            "expenses": 0.0,
            "anomalies_count": 0,
            "emergency_fund_months": emergency_fund_months,
            "active_emis": active_emis,
            "rating": "unknown",
        }

    # Score the most recent *complete* month. Scoring a stub month (a statement
    # ending on the 1st) reports a whole month's health from a day of data.
    scored = monthly_summary.get("complete_months") or months
    latest = scored[-1]
    monthly_income = monthly_summary.get("monthly_income", {})
    monthly_expenses = monthly_summary.get("monthly_expenses", {})
    income_dec = _to_decimal(monthly_income.get(latest, 0.0))
    expenses_dec = _to_decimal(monthly_expenses.get(latest, 0.0))

    # Estimate emergency fund from average monthly surplus if not supplied.
    ef_dec = _to_decimal(emergency_fund_months)
    if ef_dec == Decimal("0.00"):
        surpluses = [
            _to_decimal(monthly_income.get(m, 0.0)) - _to_decimal(monthly_expenses.get(m, 0.0))
            for m in scored
        ]
        total_surplus = sum((s for s in surpluses if s > Decimal("0.00")), Decimal("0.00"))
        avg_expense = (
            sum((_to_decimal(monthly_expenses.get(m, 0.0)) for m in scored), Decimal("0.00"))
            / Decimal(str(len(scored)))
        ) if scored else Decimal("1.00")
        if avg_expense == Decimal("0.00"):
            avg_expense = Decimal("1.00")
        ef_dec = total_surplus / avg_expense

    anomalies_count = len(anomalies or [])
    score, savings_rate = calculate_health_score(
        float(income_dec), float(expenses_dec), anomalies_count, float(ef_dec), active_emis
    )

    if score >= 75:
        rating = "healthy"
    elif score >= 50:
        rating = "okay"
    else:
        rating = "at risk"

    return {
        "score": score,
        "savings_rate": savings_rate,
        "income": _round_money(income_dec),
        "expenses": _round_money(expenses_dec),
        "anomalies_count": anomalies_count,
        "emergency_fund_months": _round_money(ef_dec),
        "active_emis": active_emis,
        "reference_month": latest,
        "rating": rating,
    }

