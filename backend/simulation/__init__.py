"""Phase 3 — Digital Financial Twin.

A deterministic, year-by-year projection engine plus scenario persistence.
"""
from __future__ import annotations

from agents.twin import (
    SAFE_WITHDRAWAL_RATE,
    Goal,
    GoalTimeline,
    RetirementEstimate,
    ScenarioInput,
    TwinResult,
    YearProjection,
    defaults_from_result,
    simulate,
)

__all__ = [
    "SAFE_WITHDRAWAL_RATE",
    "Goal",
    "GoalTimeline",
    "RetirementEstimate",
    "ScenarioInput",
    "TwinResult",
    "YearProjection",
    "defaults_from_result",
    "simulate",
]
