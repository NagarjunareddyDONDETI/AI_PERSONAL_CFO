"""Tests for Central Deterministic Tool Registry."""
from __future__ import annotations

import pytest
from tools.registry import registry


def test_tool_registry_contains_financial_tools():
    tools = registry.list_tools()
    assert len(tools) >= 8
    names = {t["name"] for t in tools}
    assert "calculate_cashflow_summary" in names
    assert "calculate_emergency_runway" in names
    assert "calculate_debt_metrics" in names
    assert "calculate_debt_payoff_timeline" in names
    assert "calculate_health_score" in names


def test_tool_registry_openai_schemas():
    schemas = registry.get_openai_schemas()
    assert len(schemas) >= 8
    for schema in schemas:
        assert schema["type"] == "function"
        assert "name" in schema["function"]
        assert "description" in schema["function"]
        assert "parameters" in schema["function"]
        assert schema["function"]["parameters"]["type"] == "object"


def test_tool_registry_execute_success():
    res = registry.execute("calculate_cashflow_summary", {"income": 80000, "expenses": 50000})
    assert res["status"] == "success"
    assert res["data"]["net_surplus"] == 30000.0
    assert res["data"]["savings_rate_pct"] == 37.5


def test_tool_registry_execute_unknown_tool():
    res = registry.execute("unknown_fake_calculator", {"param": 123})
    assert res["status"] == "error"
    assert "not registered" in res["error"]
