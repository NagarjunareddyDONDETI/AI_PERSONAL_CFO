"""Tests for Autonomous Financial Sentinels and Monitoring."""
from __future__ import annotations

import pytest
from agents import memory
from cron import monitors, scheduler
from db import database


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "cron_test.db"))
    database.init_db()
    monkeypatch.setattr(memory, "_embed", lambda user_id, items: None)


def test_daily_anomaly_monitor_no_data():
    res = monitors.run_daily_anomaly_monitor("user_with_no_data")
    assert res["status"] == "skipped"
    assert res["reason"] == "no_data"


def test_daily_anomaly_monitor_with_data():
    uid = "test_monitor_user_1"
    # Seed fake statement data with enough baseline transactions so IQR detects the outlier
    txns = [
        {"id": f"t{i}", "amount": -200 - i * 10, "category": "Food", "description": f"Lunch {i}", "date": f"2026-03-0{i+1}"}
        for i in range(8)
    ]
    txns.append({"id": "t99", "amount": -85000, "category": "Electronics", "description": "Flagship Laptop", "date": "2026-03-09"})
    database.save_result(uid, {"transactions": txns, "health_score": {"score": 75}})

    res = monitors.run_daily_anomaly_monitor(uid)
    assert res["status"] == "completed"
    assert res["anomalies_detected"] >= 1
    # Check that an insight was logged in CFO memory
    insights = database.get_memories(uid, kind="cfo_insights")
    assert any("Unusual Outflows" in ins["content"] for ins in insights)


def test_weekly_budget_pulse():
    uid = "test_monitor_user_2"
    database.save_result(uid, {
        "health_score": {
            "income": 100000,
            "expenses": 60000,
            "emergency_fund_months": 4.0,
        }
    })
    res = monitors.run_weekly_budget_pulse(uid)
    assert res["status"] == "completed"
    assert res["savings_rate_pct"] == 40.0
    assert res["net_surplus"] == 40000.0


def test_monthly_cfo_report():
    uid = "test_monitor_user_3"
    database.save_result(uid, {
        "health_score": {
            "score": 82,
            "income": 120000,
            "expenses": 70000,
        }
    })
    database.save_goal(
        user_id=uid,
        name="Emergency Fund",
        goal_type="emergency",
        target_amount=300000,
        current_saved=50000,
        target_months=12,
        monthly_contribution=10000,
    )

    res = monitors.run_monthly_cfo_report(uid)
    assert res["status"] == "completed"
    assert res["score"] == 82
    assert res["surplus"] == 50000.0
    assert res["active_goals"] >= 1


def test_scheduler_lifecycle():
    s = scheduler.AutonomousFinancialScheduler(interval_seconds=10)
    assert not s._running
    s.start()
    assert s._running
    s.stop()
    assert not s._running
