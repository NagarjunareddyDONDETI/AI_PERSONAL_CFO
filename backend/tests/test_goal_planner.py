"""Phase 9 tests: Goal Planner engine + persistence."""
from __future__ import annotations

import pytest

from agents import goal_planner as g


def test_goal_types_include_presets():
    ids = {t["id"] for t in g.goal_types()}
    for expected in ("emergency_fund", "car", "house", "retirement", "custom"):
        assert expected in ids


def test_fixed_timeline_computes_required_monthly():
    p = g.plan_goal(
        goal_type="car", target_amount=800000, current_saved=100000,
        target_months=36, monthly_surplus=25000, emergency_fund_months=4,
    )
    assert p["timeline_months"] == 36
    assert p["required_monthly"] > 0
    # Surplus comfortably covers the requirement → high probability, low risk.
    assert p["completion_probability"] >= 0.9
    assert p["risk"] == "Low"
    assert p["trajectory"][0]["month"] == 0
    assert p["trajectory"][-1]["month"] == 36


def test_underfunded_goal_has_low_probability():
    p = g.plan_goal(
        goal_type="house", target_amount=5_000_000, current_saved=0,
        target_months=24, monthly_surplus=5000, emergency_fund_months=1,
    )
    # Required monthly hugely exceeds the surplus → low odds, high risk.
    assert p["completion_probability"] < 0.5
    assert p["risk"] == "High"


def test_auto_timeline_from_surplus():
    p = g.plan_goal(
        goal_type="vacation", target_amount=120000, current_saved=0,
        monthly_surplus=10000, emergency_fund_months=6,
    )
    assert p["timeline_months"] >= 1
    assert p["reachable"] is True


def test_unreachable_when_no_contribution_no_growth():
    p = g.plan_goal(
        goal_type="custom", target_amount=100000, current_saved=0,
        monthly_contribution=0, monthly_surplus=0, annual_return=0.0,
    )
    assert p["reachable"] is False
    assert p["completion_probability"] <= 0.1


def test_progress_pct():
    p = g.plan_goal(
        goal_type="emergency_fund", target_amount=100000, current_saved=25000,
        target_months=10, monthly_surplus=10000,
    )
    assert p["progress_pct"] == 25.0


def test_emergency_fund_fragility_penalty():
    strong = g.plan_goal(goal_type="car", target_amount=300000, current_saved=0,
                          target_months=12, monthly_surplus=30000, emergency_fund_months=6)
    weak = g.plan_goal(goal_type="car", target_amount=300000, current_saved=0,
                       target_months=12, monthly_surplus=30000, emergency_fund_months=1)
    assert weak["completion_probability"] < strong["completion_probability"]


def test_already_reached_goal():
    p = g.plan_goal(goal_type="custom", target_amount=1000, current_saved=1000,
                    target_months=12, monthly_surplus=5000)
    assert p["required_monthly"] == 0.0
    assert p["progress_pct"] == 100.0


def test_surplus_from_result():
    surplus, ef = g.surplus_from_result(
        {"health_score": {"income": 90000, "expenses": 60000, "emergency_fund_months": 2.5}}
    )
    assert surplus == 30000
    assert ef == 2.5


def test_goal_persistence(tmp_path, monkeypatch):
    from db import database

    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "goals.db"))
    database.init_db()
    uid = "goal_user"
    assert database.list_goals(uid) == []
    gid = database.save_goal(uid, "New car", "car", 800000, 50000, 36, None)
    rows = database.list_goals(uid)
    assert len(rows) == 1 and rows[0]["name"] == "New car"
    assert database.delete_goal(gid, uid) is True
    assert database.list_goals(uid) == []


# --- Frontend contract: these keys are consumed by GoalPlannerPanel.tsx and
# declared in api.ts GoalPlan. Drift here silently breaks the UI. ---
_PLAN_KEYS = {
    "goal_type", "label", "icon", "target_amount", "current_saved", "remaining",
    "annual_return", "timeline_months", "months_to_reach", "target_date",
    "required_monthly", "monthly_contribution", "monthly_surplus",
    "shortfall_monthly", "completion_probability", "risk", "reachable",
    "on_track", "projected_label", "trajectory", "progress_pct",
}

_PLAN_CASES = [
    dict(goal_type="car", target_amount=800000, current_saved=100000,
         target_months=36, monthly_surplus=25000, emergency_fund_months=4),
    dict(goal_type="house", target_amount=5_000_000, current_saved=0,
         target_months=24, monthly_surplus=5000, emergency_fund_months=1),
    dict(goal_type="vacation", target_amount=120000, current_saved=0,
         monthly_surplus=10000, emergency_fund_months=6),
    dict(goal_type="custom", target_amount=100000, current_saved=0,
         monthly_contribution=0, monthly_surplus=0),
    dict(goal_type="custom", target_amount=1000, current_saved=1000,
         target_months=12, monthly_surplus=5000),
]


@pytest.mark.parametrize("kwargs", _PLAN_CASES)
def test_every_branch_returns_the_full_key_set(kwargs):
    plan = g.plan_goal(**kwargs)
    assert _PLAN_KEYS.issubset(plan), _PLAN_KEYS - set(plan)
    assert plan["target_date"]
    # The sparkline plots `balance`; renaming it blanks the chart.
    assert plan["trajectory"]
    assert all({"month", "balance", "target"} <= set(p) for p in plan["trajectory"])


def test_goal_types_expose_preset_defaults():
    for t in g.goal_types():
        assert t["default_months"] > 0
        assert 0.0 <= t["assumed_return"] <= 1.0
        assert t["label"] and t["icon"]


def test_target_date_formatting():
    from datetime import date

    assert g._target_date(None) == "Beyond horizon"
    assert g._target_date(0) == "This month"
    assert g._target_date(1, date(2026, 12, 15)) == "Jan 2027"
    assert g._target_date(12, date(2026, 1, 10)) == "Jan 2027"
    assert g._target_date(36, date(2026, 3, 1)) == "Mar 2029"


def test_annual_return_shortens_timeline():
    flat = g.plan_goal(goal_type="retirement", target_amount=1_000_000,
                       current_saved=0, monthly_contribution=5000, annual_return=0.0)
    grown = g.plan_goal(goal_type="retirement", target_amount=1_000_000,
                        current_saved=0, monthly_contribution=5000, annual_return=0.10)
    assert grown["months_to_reach"] < flat["months_to_reach"]
    assert grown["annual_return"] == 0.1


def test_annual_return_persists(tmp_path, monkeypatch):
    from db import database

    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "goals.db"))
    database.init_db()
    database.save_goal("u", "Retire", "retirement", 1_000_000, 0, 240, None, 0.08)
    assert database.list_goals("u")[0]["annual_return"] == 0.08


def test_migration_adds_annual_return_to_legacy_table(tmp_path, monkeypatch):
    """A DB created before the column existed must upgrade, not crash."""
    import sqlite3

    from db import database

    path = str(tmp_path / "legacy.db")
    monkeypatch.setattr(database, "_DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE financial_goals (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id TEXT NOT NULL, name TEXT NOT NULL, goal_type TEXT NOT NULL, "
            "target_amount REAL NOT NULL, current_saved REAL NOT NULL DEFAULT 0, "
            "target_months INTEGER, monthly_contribution REAL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO financial_goals (user_id, name, goal_type, target_amount, "
            "current_saved, created_at) VALUES ('old','Legacy','car',100,10,'2026-01-01')"
        )

    database.init_db()
    rows = database.list_goals("old")
    assert len(rows) == 1
    assert rows[0]["annual_return"] == 0.0
    database.init_db()  # idempotent
