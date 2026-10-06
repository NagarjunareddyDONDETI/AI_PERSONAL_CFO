"""Central Deterministic Tool Registry for AI Personal CFO.

Inspired by Hermes Agent's registry pattern, this module provides:
1. Tool registration with typed metadata and parameter schemas.
2. Standardized execution with error wrapping and JSON serialization.
3. OpenAI-compatible tool schemas for LLM tool calling.
4. Guaranteed deterministic execution — mathematical safety invariants enforced.
"""
from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from tools import financial_tools

logger = logging.getLogger("tools.registry")


@dataclass
class ToolDefinition:
    name: str
    description: str
    category: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    requires_data: list[str] = field(default_factory=list)

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """Registry managing all deterministic financial tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        category: str,
        parameters: dict[str, Any],
        handler: Callable[..., Any],
        requires_data: Optional[list[str]] = None,
    ) -> None:
        """Register a deterministic tool."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            category=category,
            parameters=parameters,
            handler=handler,
            requires_data=requires_data or [],
        )
        logger.debug("Registered financial tool: %s (%s)", name, category)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "parameters": t.parameters,
                "requires_data": t.requires_data,
            }
            for t in self._tools.values()
        ]

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        return [t.to_openai_schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool by name with arguments and return validated JSON result."""
        tool_def = self._tools.get(name)
        if not tool_def:
            return {
                "status": "error",
                "tool": name,
                "error": f"Tool '{name}' is not registered in Financial Tool Registry.",
                "source": "deterministic_engine",
            }

        try:
            # Type-safe parameter passing
            sig = inspect.signature(tool_def.handler)
            bound_args = {}
            for param_name, param in sig.parameters.items():
                if param_name in args:
                    bound_args[param_name] = args[param_name]
                elif param.default is not inspect.Parameter.empty:
                    bound_args[param_name] = param.default

            res = tool_def.handler(**bound_args)
            if isinstance(res, dict):
                return res
            return {"status": "success", "tool": name, "data": res, "source": "deterministic_engine"}
        except Exception as exc:  # noqa: BLE001
            logger.error("Tool execution error in '%s': %s", name, exc, exc_info=True)
            return {
                "status": "error",
                "tool": name,
                "error": str(exc),
                "source": "deterministic_engine",
            }


# Singleton registry instance
registry = ToolRegistry()


# --------------------------------------------------------------------------- #
# Built-in Core Tool Registration
# --------------------------------------------------------------------------- #

def _register_builtin_tools() -> None:
    # 1. Cashflow Summary
    registry.register(
        name="calculate_cashflow_summary",
        description="Calculate exact monthly income, expenses, net cashflow surplus/deficit, savings rate, and burn ratio.",
        category="cashflow",
        parameters={
            "type": "object",
            "properties": {
                "income": {"type": "number", "description": "Monthly total income"},
                "expenses": {"type": "number", "description": "Monthly total expenses"},
            },
            "required": ["income", "expenses"],
        },
        handler=financial_tools.calculate_cashflow_summary,
        requires_data=["income", "expenses"],
    )

    # 2. Emergency Runway
    registry.register(
        name="calculate_emergency_runway",
        description="Compute emergency fund coverage in months, funding gap against target, and status rating.",
        category="risk",
        parameters={
            "type": "object",
            "properties": {
                "current_savings": {"type": "number", "description": "Current total liquid savings/emergency reserve"},
                "monthly_expenses": {"type": "number", "description": "Average monthly living expenses"},
                "target_months": {"type": "number", "description": "Target emergency runway in months (default 6)"},
            },
            "required": ["current_savings", "monthly_expenses"],
        },
        handler=financial_tools.calculate_emergency_runway,
        requires_data=["current_savings", "monthly_expenses"],
    )

    # 3. Debt Metrics & DTI
    registry.register(
        name="calculate_debt_metrics",
        description="Compute total outstanding debt, monthly EMI obligations, and Debt-to-Income (DTI) percentage.",
        category="debt",
        parameters={
            "type": "object",
            "properties": {
                "monthly_income": {"type": "number", "description": "Gross monthly income"},
                "debts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "balance": {"type": "number"},
                            "monthly_payment": {"type": "number"},
                            "interest_rate": {"type": "number"},
                        },
                        "required": ["name", "balance", "monthly_payment"],
                    },
                    "description": "List of active debts with balance and monthly payments",
                },
            },
            "required": ["monthly_income", "debts"],
        },
        handler=financial_tools.calculate_debt_metrics,
        requires_data=["monthly_income", "debts"],
    )

    # 4. Compound Growth Projection
    registry.register(
        name="calculate_compound_growth",
        description="Project investment growth with compound interest and regular monthly contributions over specified years.",
        category="investment",
        parameters={
            "type": "object",
            "properties": {
                "principal": {"type": "number", "description": "Starting principal amount"},
                "monthly_contribution": {"type": "number", "description": "Monthly investment addition"},
                "annual_rate_pct": {"type": "number", "description": "Expected annual return rate percentage (e.g. 10.0 for 10%)"},
                "years": {"type": "integer", "description": "Investment horizon in years"},
            },
            "required": ["principal", "monthly_contribution", "annual_rate_pct", "years"],
        },
        handler=financial_tools.calculate_compound_growth,
        requires_data=["principal", "monthly_contribution", "annual_rate_pct", "years"],
    )

    # 5. Debt Payoff Optimizer (Avalanche vs Snowball)
    registry.register(
        name="calculate_debt_payoff_timeline",
        description="Calculate exact payoff timeline, interest saved, and monthly amortization using Avalanche or Snowball strategy.",
        category="debt",
        parameters={
            "type": "object",
            "properties": {
                "debts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "balance": {"type": "number"},
                            "monthly_payment": {"type": "number"},
                            "interest_rate": {"type": "number"},
                        },
                        "required": ["name", "balance", "monthly_payment", "interest_rate"],
                    },
                },
                "extra_monthly_payment": {"type": "number", "description": "Extra cash allocated to debt reduction monthly"},
                "strategy": {"type": "string", "enum": ["avalanche", "snowball"], "description": "avalanche (highest interest first) or snowball (lowest balance first)"},
            },
            "required": ["debts"],
        },
        handler=financial_tools.calculate_debt_payoff_timeline,
        requires_data=["debts"],
    )

    # 6. Health Score Calculation
    registry.register(
        name="calculate_health_score",
        description="Compute the exact 0-100 financial health score and itemized component penalties.",
        category="health",
        parameters={
            "type": "object",
            "properties": {
                "income": {"type": "number", "description": "Monthly income"},
                "expenses": {"type": "number", "description": "Monthly expenses"},
                "anomalies_count": {"type": "integer", "description": "Count of detected spending anomalies"},
                "emergency_fund_months": {"type": "number", "description": "Months of emergency fund runway"},
                "active_emis": {"type": "integer", "description": "Count of active EMIs"},
            },
            "required": ["income", "expenses"],
        },
        handler=financial_tools.calculate_health_score_deterministic,
        requires_data=["income", "expenses"],
    )

    # 7. Anomaly Detection
    registry.register(
        name="detect_anomalies",
        description="Detect spending anomalies and spikes using statistical Interquartile Range (IQR).",
        category="anomaly",
        parameters={
            "type": "object",
            "properties": {
                "transactions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "date": {"type": "string"},
                            "description": {"type": "string"},
                            "amount": {"type": "number"},
                            "category": {"type": "string"},
                        },
                        "required": ["date", "description", "amount"],
                    },
                },
                "iqr_multiplier": {"type": "number", "description": "IQR multiplier for anomaly cutoff (default 1.5)"},
            },
            "required": ["transactions"],
        },
        handler=financial_tools.detect_anomalies_deterministic,
        requires_data=["transactions"],
    )

    # 8. Goal Contribution Planner
    registry.register(
        name="plan_goal_contributions",
        description="Determine required monthly savings and investment returns to hit a financial milestone by a target deadline.",
        category="goals",
        parameters={
            "type": "object",
            "properties": {
                "target_amount": {"type": "number", "description": "Total target goal amount"},
                "current_saved": {"type": "number", "description": "Amount currently saved towards goal"},
                "target_months": {"type": "integer", "description": "Target timeline in months"},
                "expected_annual_return_pct": {"type": "number", "description": "Expected annual investment return percentage"},
            },
            "required": ["target_amount"],
        },
        handler=financial_tools.plan_goal_contributions,
        requires_data=["target_amount"],
    )


# Auto-register at import time
_register_builtin_tools()
