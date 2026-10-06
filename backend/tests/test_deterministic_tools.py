"""Tests for deterministic financial calculation engine.

Validates that all mathematical operations adhere strictly to the Financial Safety Principle:
zero LLM numerical hallucination, division-by-zero guards, bounds validation, and checksum verification.
"""
from __future__ import annotations

import pytest
from tools import financial_tools


def test_calculate_cashflow_summary():
    res = financial_tools.calculate_cashflow_summary(income=100000, expenses=65000)
    assert res["status"] == "success"
    data = res["data"]
    assert data["monthly_income"] == 100000.0
    assert data["monthly_expenses"] == 65000.0
    assert data["net_surplus"] == 35000.0
    assert data["savings_rate_pct"] == 35.0
    assert data["burn_ratio_pct"] == 65.0
    assert data["is_cashflow_positive"] is True
    assert res["validation_checks"]["math_verified"] is True


def test_calculate_cashflow_summary_zero_income():
    res = financial_tools.calculate_cashflow_summary(income=0, expenses=25000)
    assert res["status"] == "success"
    data = res["data"]
    assert data["savings_rate_pct"] == 0.0
    assert data["burn_ratio_pct"] == 100.0
    assert data["net_surplus"] == -25000.0
    assert data["is_cashflow_positive"] is False


def test_calculate_emergency_runway():
    res = financial_tools.calculate_emergency_runway(
        current_savings=150000,
        monthly_expenses=50000,
        target_months=6,
    )
    assert res["status"] == "success"
    data = res["data"]
    assert data["months_covered"] == 3.0
    assert data["target_amount"] == 300000.0
    assert data["shortfall"] == 150000.0
    assert data["status"] == "moderate"


def test_calculate_emergency_runway_zero_expenses():
    res = financial_tools.calculate_emergency_runway(current_savings=100000, monthly_expenses=0)
    assert res["status"] == "success"
    data = res["data"]
    assert data["months_covered"] == 999.0
    assert data["status"] == "adequate"


def test_calculate_debt_metrics():
    debts = [
        {"name": "Credit Card", "balance": 50000, "monthly_payment": 2500, "interest_rate": 36.0},
        {"name": "Personal Loan", "balance": 150000, "monthly_payment": 4500, "interest_rate": 14.0},
    ]
    res = financial_tools.calculate_debt_metrics(monthly_income=100000, debts=debts)
    assert res["status"] == "success"
    data = res["data"]
    assert data["total_debt_balance"] == 200000.0
    assert data["total_monthly_emi"] == 7000.0
    assert data["dti_pct"] == 7.0
    assert data["debt_risk_level"] == "low"


def test_calculate_debt_payoff_timeline_avalanche_vs_snowball():
    debts = [
        {"name": "Credit Card", "balance": 50000, "interest_rate": 36.0, "monthly_payment": 2500},
        {"name": "Personal Loan", "balance": 150000, "interest_rate": 14.0, "monthly_payment": 4500},
    ]
    res_avalanche = financial_tools.calculate_debt_payoff_timeline(debts, extra_monthly_payment=3000, strategy="avalanche")
    assert res_avalanche["status"] == "success"
    av_data = res_avalanche["data"]
    assert av_data["total_principal_paid"] == 200000.0
    assert av_data["total_months"] > 0
    assert av_data["total_interest_paid"] > 0

    res_snowball = financial_tools.calculate_debt_payoff_timeline(debts, extra_monthly_payment=3000, strategy="snowball")
    assert res_snowball["status"] == "success"
    sn_data = res_snowball["data"]
    assert sn_data["total_months"] > 0


def test_calculate_health_score_deterministic():
    res = financial_tools.calculate_health_score_deterministic(
        income=120000,
        expenses=60000,
        emergency_fund_months=5.5,
        anomalies_count=0,
        active_emis=0,
    )
    assert res["status"] == "success"
    data = res["data"]
    assert data["score"] == 100
    assert data["rating"] == "healthy"
    assert data["savings_rate_pct"] == 50.0


def test_detect_anomalies_deterministic():
    txns = [
        {"date": "2026-03-01", "description": "Lunch", "amount": -500, "category": "Food"},
        {"date": "2026-03-02", "description": "Dinner", "amount": -450, "category": "Food"},
        {"date": "2026-03-03", "description": "Groceries", "amount": -520, "category": "Food"},
        {"date": "2026-03-04", "description": "Cafe", "amount": -480, "category": "Food"},
        {"date": "2026-03-05", "description": "Snacks", "amount": -510, "category": "Food"},
        {"date": "2026-03-06", "description": "Luxury Watch", "amount": -95000, "category": "Shopping"},
    ]
    res = financial_tools.detect_anomalies_deterministic(txns, iqr_multiplier=1.5)
    assert res["status"] == "success"
    data = res["data"]
    assert data["anomalies_found"] >= 1
    anom = data["anomalies"][0]
    assert anom["description"] == "Luxury Watch"
    assert anom["amount"] == 95000.0


def test_calculate_compound_growth():
    res = financial_tools.calculate_compound_growth(
        principal=100000,
        monthly_contribution=10000,
        annual_rate_pct=12.0,
        years=5,
    )
    assert res["status"] == "success"
    data = res["data"]
    assert data["years"] == 5
    assert data["total_contributed"] == 700000.0  # 100k + (10k * 60)
    assert data["final_value"] > 700000.0
    assert data["total_interest_earned"] > 0
    assert len(data["trajectory"]) == 5


def test_plan_goal_contributions():
    res = financial_tools.plan_goal_contributions(
        target_amount=1500000,
        current_saved=300000,
        target_months=36,
        expected_annual_return_pct=8.0,
    )
    assert res["status"] == "success"
    data = res["data"]
    assert data["target_amount"] == 1500000.0
    assert data["required_monthly_savings"] > 0
    assert data["already_achieved"] is False
