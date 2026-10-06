"""Tests for Hermes-style Financial Skills system."""
from __future__ import annotations

import pytest
from skills.skill_registry import skill_registry, FinancialSkill


def test_skills_loaded_from_directory():
    skills = skill_registry.list_skills()
    assert len(skills) >= 9
    skill_names = {s["name"] for s in skills}
    expected = {
        "budget-analysis",
        "cashflow-forecast",
        "emergency-fund-audit",
        "debt-payoff-optimizer",
        "investment-risk-allocation",
        "financial-health-assessment",
        "lifestyle-creep-detector",
        "tax-optimization-strategy",
        "goal-feasibility-planner",
    }
    assert expected.issubset(skill_names)


def test_get_individual_skill():
    skill = skill_registry.get_skill("budget-analysis")
    assert skill is not None
    assert skill.name == "budget-analysis"
    assert "calculate_cashflow_summary" in skill.required_tools
    assert skill.category == "budgeting"
    assert len(skill.safety_constraints) > 0
    assert "Never guess" in skill.safety_constraints[0] or "deterministic" in skill.safety_constraints[0].lower()


def test_match_skill_by_query():
    skill = skill_registry.match_skill("Can you audit my emergency fund runway?")
    assert skill is not None
    assert skill.name == "emergency-fund-audit"

    skill_debt = skill_registry.match_skill("How quickly can I pay off my credit card debt with avalanche?")
    assert skill_debt is not None
    assert skill_debt.name == "debt-payoff-optimizer"


def test_skill_prompt_formatting():
    skill = skill_registry.get_skill("emergency-fund-audit")
    assert skill is not None
    prompt = skill.get_prompt_instructions()
    assert "Active Financial Skill: emergency-fund-audit" in prompt
    assert "calculate_emergency_runway" in prompt
    assert "Safety Constraints" in prompt
