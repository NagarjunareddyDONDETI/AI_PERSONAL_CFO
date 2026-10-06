"""Tests for categorized long-term memory and CFO insight logging."""
from __future__ import annotations

import pytest
from agents import memory
from db import database


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "cfo_mem.db"))
    database.init_db()
    monkeypatch.setattr(memory, "_embed", lambda user_id, items: None)


def test_user_profile_persistence():
    uid = "test_user_profile_123"
    profile_data = {
        "monthly_salary": 150000,
        "risk_tolerance": "moderate",
        "dependents": 2,
        "primary_goal": "Retire Early",
    }
    database.set_user_profile(uid, profile_data)
    stored = database.get_user_profile(uid)
    assert stored["monthly_salary"] == 150000
    assert stored["risk_tolerance"] == "moderate"
    assert stored["primary_goal"] == "Retire Early"


def test_cfo_insight_recording():
    uid = "test_user_insight_456"
    database.record_cfo_insight(
        user_id=uid,
        title="Excessive Food Spending Alert",
        recommendation="Food spending exceeded 25% of monthly budget. Suggest capping dining out.",
        confidence=0.91,
        source_agent="Budget & Savings Strategist",
        metadata={"category": "Food", "overage": 4500},
    )
    insights = database.get_memories(uid, kind="cfo_insights")
    assert len(insights) >= 1
    top = insights[0]
    assert "Excessive Food Spending" in top["content"]
    assert top["data"]["confidence"] == 0.91
    assert top["data"]["source_agent"] == "Budget & Savings Strategist"


def test_get_categorized_memories():
    uid = "test_user_cat_789"
    database.upsert_memory(uid, "user_profile", "prof_core", "Profile: Age 30", {"age": 30})
    database.upsert_memory(uid, "financial_goals", "goal_house", "Goal: Buy House", {"target": 5000000})
    database.upsert_memory(uid, "cfo_insights", "ins_1", "Insight: Save 20%", {"rate": 20})

    categorized = database.get_categorized_memories(uid)
    assert "user_profile" in categorized
    assert "financial_goals" in categorized
    assert "cfo_insights" in categorized
    assert len(categorized["user_profile"]) >= 1
    assert len(categorized["financial_goals"]) >= 1


def test_memory_recall_context():
    uid = "test_user_recall_999"
    database.upsert_memory(uid, "preference", "pref_1", "Prefers conservative debt payoff", {})
    database.upsert_memory(uid, "goal", "goal_1", "Goal: Emergency fund 6 months", {})

    context = memory.recall_context(uid)
    assert "(preference)" in context or "(goal)" in context
    assert "emergency fund" in context.lower() or "conservative" in context.lower()
