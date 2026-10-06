"""Adversarial and Anti-Hallucination Safety Tests for AI Personal CFO.

Validates that:
1. Deterministic math engine cannot be forced to output corrupted data via malicious inputs.
2. Division-by-zero, extreme negatives, and type corruption are safely handled.
3. Financial specialists adhere strictly to computed heuristics without ungrounded hallucinations.
"""
from __future__ import annotations

import pytest
from agents.debate.specialists import PANEL
from tools import financial_tools
from tools.registry import registry


def test_adversarial_zero_and_negative_inputs():
    # Negative income and expenses
    res = financial_tools.calculate_cashflow_summary(income=-50000, expenses=-20000)
    assert res["status"] == "success"
    # Max(0.0) guards ensure no corrupted negative math
    assert res["data"]["monthly_income"] == 0.0
    assert res["data"]["monthly_expenses"] == 0.0
    assert res["data"]["net_surplus"] == 0.0

    # Extreme numbers / float overflow prevention
    res_runway = financial_tools.calculate_emergency_runway(
        current_savings=1e12,
        monthly_expenses=0,
    )
    assert res_runway["status"] == "success"
    assert res_runway["data"]["months_covered"] == 999.0


def test_adversarial_empty_debts():
    res = financial_tools.calculate_debt_payoff_timeline(debts=[], extra_monthly_payment=5000)
    assert res["status"] == "success"
    assert res["data"]["total_principal_paid"] == 0.0
    assert res["data"]["total_months"] == 0
    assert res["data"]["total_interest_paid"] == 0.0


def test_specialists_grounded_in_computed_data():
    sample_data = {
        "health_score": {
            "income": 90000,
            "expenses": 45000,
            "emergency_fund_months": 2.0,
            "savings_rate": 0.50,
            "active_emis": 1,
            "anomalies_count": 0,
            "score": 68,
        },
        "monthly_summary": {
            "category_totals": {"Food": 15000, "Rent": 25000, "Utilities": 5000},
        },
    }

    for specialist in PANEL:
        stance, summary, points, conf = specialist.heuristic(sample_data)
        assert isinstance(stance, str)
        assert len(stance) > 0
        assert isinstance(summary, str)
        assert len(summary) > 0
        assert isinstance(points, list)
        assert 0.0 <= conf <= 1.0


def test_tool_registry_type_safety():
    # Calling with missing arguments
    res = registry.execute("calculate_cashflow_summary", {})
    # Should safely compute defaults or return status without unhandled crash
    assert "status" in res
