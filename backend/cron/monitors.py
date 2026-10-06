"""Autonomous Financial Monitors for AI Personal CFO.

Implements periodic financial sentinel checks inspired by Hermes Agent's
autonomous cron scheduling. Every monitor is 100% deterministic and logs
verified insights into the user's persistent CFO memory.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db import database
from tools import financial_tools

logger = logging.getLogger("cron.monitors")


def _inr(n: float) -> str:
    return f"Rs.{abs(float(n or 0)):,.0f}"


def run_daily_anomaly_monitor(user_id: str) -> dict[str, Any]:
    """Daily check for sudden spending spikes or statistical anomalies."""
    result = database.get_result(user_id)
    if not result:
        return {"status": "skipped", "reason": "no_data", "anomalies_detected": 0}

    txns = result.get("transactions", []) or []
    anom_res = financial_tools.detect_anomalies_deterministic(txns, iqr_multiplier=1.5)
    anomalies = anom_res.get("data", {}).get("anomalies", [])

    if anomalies:
        top_anom = anomalies[0]
        title = f"Daily Alert: {len(anomalies)} Unusual Outflows Detected"
        rec = f"Unusual spend on '{top_anom.get('description')}' of {_inr(top_anom.get('amount'))} is {_inr(top_anom.get('deviation_above_threshold'))} above normal threshold."
        database.record_cfo_insight(
            user_id=user_id,
            title=title,
            recommendation=rec,
            confidence=0.92,
            source_agent="Risk & Anomaly Sentinel",
            metadata={"anomalies_count": len(anomalies), "top_anomaly": top_anom},
        )
        logger.info("Daily anomaly monitor flagged %d items for user=%s", len(anomalies), user_id)

    return {
        "status": "completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "anomalies_detected": len(anomalies),
        "anomalies": anomalies,
    }


def run_weekly_budget_pulse(user_id: str) -> dict[str, Any]:
    """Weekly pulse checking budget pacing, savings rate, and emergency buffer."""
    result = database.get_result(user_id)
    if not result:
        return {"status": "skipped", "reason": "no_data"}

    hs = result.get("health_score", {}) or {}
    income = float(hs.get("income", 0.0) or 0.0)
    expenses = float(hs.get("expenses", 0.0) or 0.0)
    ef_months = float(hs.get("emergency_fund_months", 0.0) or 0.0)

    cf = financial_tools.calculate_cashflow_summary(income, expenses).get("data", {})
    rate = cf.get("savings_rate_pct", 0.0)
    surplus = cf.get("net_surplus", 0.0)

    title = f"Weekly Budget Pulse: {rate:.1f}% Savings Rate"
    if rate >= 20.0:
        rec = f"Your savings pace is strong at {rate:.1f}% with {_inr(surplus)} monthly surplus. Automated transfers are recommended."
        conf = 0.88
    else:
        gap = 20.0 - rate
        rec = f"Savings rate is currently {rate:.1f}% ({gap:.1f}% below target). Review top discretionary categories to free up cashflow."
        conf = 0.85

    database.record_cfo_insight(
        user_id=user_id,
        title=title,
        recommendation=rec,
        confidence=conf,
        source_agent="Budget & Savings Strategist",
        metadata={"savings_rate_pct": rate, "net_surplus": surplus, "emergency_months": ef_months},
    )

    return {
        "status": "completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "savings_rate_pct": rate,
        "net_surplus": surplus,
    }


def run_monthly_cfo_report(user_id: str) -> dict[str, Any]:
    """Monthly executive financial health, net worth, and goal progression report."""
    result = database.get_result(user_id)
    if not result:
        return {"status": "skipped", "reason": "no_data"}

    hs = result.get("health_score", {}) or {}
    score = int(hs.get("score", 0) or 0)
    income = float(hs.get("income", 0.0) or 0.0)
    expenses = float(hs.get("expenses", 0.0) or 0.0)
    surplus = max(0.0, income - expenses)
    goals = database.list_goals(user_id)

    title = f"Monthly Executive CFO Report (Health Score: {score}/100)"
    rec = f"Monthly income of {_inr(income)} against {_inr(expenses)} expenses generated {_inr(surplus)} surplus. Managing {len(goals)} active financial goals."

    database.record_cfo_insight(
        user_id=user_id,
        title=title,
        recommendation=rec,
        confidence=0.95,
        source_agent="Chief Financial Officer (CFO)",
        metadata={"score": score, "income": income, "expenses": expenses, "goals_count": len(goals)},
    )

    return {
        "status": "completed",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "score": score,
        "income": income,
        "expenses": expenses,
        "surplus": surplus,
        "active_goals": len(goals),
    }
