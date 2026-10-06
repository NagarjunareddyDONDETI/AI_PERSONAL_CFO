"""What-If purchase simulator (Phase 5).

Deterministic math only. Compares paying in full vs EMI, running both
scenarios through the same health-score function for comparable scores.
Uses Decimal precision for financial calculations.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any

from agents.health_score import calculate_health_score

FLAT_INTEREST_RATE = Decimal("0.11")  # ~11% flat interest for EMI realism


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


def simulate_purchase(
    purchase_amount: float,
    monthly_summary: dict,
    health_score: dict,
    tenure_months: int = 12,
    current_savings: float | None = None,
) -> dict:
    purchase_dec = max(Decimal("0.00"), _to_decimal(purchase_amount))
    tenure_int = max(1, int(tenure_months or 12))
    tenure_dec = Decimal(str(tenure_int))

    monthly_income_dec = max(Decimal("0.00"), _to_decimal(health_score.get("income", 0.0) if isinstance(health_score, dict) else 0.0))
    monthly_expenses_dec = max(Decimal("0.00"), _to_decimal(health_score.get("expenses", 0.0) if isinstance(health_score, dict) else 0.0))
    if monthly_expenses_dec == Decimal("0.00"):
        monthly_expenses_dec = Decimal("1.00")

    # Estimate current savings from cumulative surplus if not provided.
    if current_savings is None:
        inc_dict = monthly_summary.get("monthly_income", {}) if isinstance(monthly_summary, dict) else {}
        exp_dict = monthly_summary.get("monthly_expenses", {}) if isinstance(monthly_summary, dict) else {}
        total_income = sum((_to_decimal(v) for v in inc_dict.values()), Decimal("0.00"))
        total_expenses = sum((_to_decimal(v) for v in exp_dict.values()), Decimal("0.00"))
        savings_dec = max(Decimal("0.00"), total_income - total_expenses)
    else:
        savings_dec = max(Decimal("0.00"), _to_decimal(current_savings))

    anomalies_count = int(health_score.get("anomalies_count", 0) if isinstance(health_score, dict) else 0)
    active_emis = int(health_score.get("active_emis", 0) if isinstance(health_score, dict) else 0)

    # --- Scenario A: Pay in full ---
    new_savings_full = savings_dec - purchase_dec
    ef_months_full = new_savings_full / monthly_expenses_dec if monthly_expenses_dec > Decimal("0.00") else Decimal("0.00")
    score_full, sr_full = calculate_health_score(
        float(monthly_income_dec),
        float(monthly_expenses_dec),
        anomalies_count,
        float(ef_months_full),
        active_emis,
    )

    # --- Scenario B: EMI ---
    interest_mult = Decimal("1.00") + FLAT_INTEREST_RATE * (tenure_dec / Decimal("12.00"))
    total_with_interest = purchase_dec * interest_mult
    emi_monthly = total_with_interest / tenure_dec
    expenses_with_emi = monthly_expenses_dec + emi_monthly
    ef_months_emi = savings_dec / expenses_with_emi if expenses_with_emi > Decimal("0.00") else Decimal("0.00")
    score_emi, sr_emi = calculate_health_score(
        float(monthly_income_dec),
        float(expenses_with_emi),
        anomalies_count,
        float(ef_months_emi),
        active_emis + 1,
    )

    interest_paid = total_with_interest - purchase_dec

    return {
        "purchase_amount": _round_money(purchase_dec),
        "tenure_months": tenure_int,
        "current_savings": _round_money(savings_dec),
        "monthly_expenses": _round_money(monthly_expenses_dec),
        "pay_full": {
            "label": "Pay in Full",
            "new_savings": _round_money(new_savings_full),
            "emergency_fund_months": _round_money(ef_months_full),
            "monthly_outflow": _round_money(monthly_expenses_dec),
            "savings_rate": round(sr_full, 4),
            "health_score": score_full,
            "affordable": new_savings_full >= Decimal("0.00"),
        },
        "emi": {
            "label": "EMI",
            "emi_monthly": _round_money(emi_monthly),
            "total_paid": _round_money(total_with_interest),
            "interest_paid": _round_money(interest_paid),
            "emergency_fund_months": _round_money(ef_months_emi),
            "monthly_outflow": _round_money(expenses_with_emi),
            "savings_rate": round(sr_emi, 4),
            "health_score": score_emi,
        },
        "recommendation": "pay_full" if score_full >= score_emi else "emi",
    }

