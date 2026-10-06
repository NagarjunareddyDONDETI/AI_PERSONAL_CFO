"""Phase 3 — Digital Financial Twin.

A deterministic simulation engine that projects a user's current financial
state into the future. Every number is computed explicitly (no LLM, no random
noise) using Decimal precision so results are reproducible and explainable:

  current state → salary growth → expense growth → inflation →
  investment growth → emergency fund → retirement estimate → goal timelines

Supports multiple named scenarios; the API layer handles save/compare.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel, Field

# Safe withdrawal rate used for the retirement sustainability estimate.
SAFE_WITHDRAWAL_RATE = 0.04


def _to_decimal(val: Any) -> Decimal:
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    try:
        s = str(val).strip()
        return Decimal(s) if s else Decimal("0.00")
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def _round_money(d: Decimal) -> float:
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class Goal(BaseModel):
    name: str
    target_amount: float = Field(gt=0)


class ScenarioInput(BaseModel):
    """All assumptions for one projection. Rates are annual decimals (0.08 = 8%)."""

    name: str = "Base scenario"
    years: int = Field(default=20, ge=1, le=60)

    monthly_income: float = Field(ge=0)
    monthly_expenses: float = Field(ge=0)
    current_savings: float = Field(default=0.0, ge=0)

    salary_growth: float = Field(default=0.08, ge=-0.5, le=1.0)
    expense_growth: float = Field(default=0.06, ge=-0.5, le=1.0)
    inflation: float = Field(default=0.05, ge=0.0, le=0.5)
    investment_return: float = Field(default=0.10, ge=-0.5, le=1.0)

    current_age: Optional[int] = Field(default=None, ge=0, le=100)
    retirement_age: Optional[int] = Field(default=None, ge=1, le=100)

    goals: list[Goal] = Field(default_factory=list)


class YearProjection(BaseModel):
    year: int
    age: Optional[int] = None
    annual_income: float
    annual_expenses: float
    annual_savings: float
    invested: float           # cumulative portfolio value (nominal)
    net_worth: float          # nominal
    real_net_worth: float     # inflation-adjusted to today's money
    emergency_fund_months: float


class GoalTimeline(BaseModel):
    name: str
    target_amount: float
    reached: bool
    year_reached: Optional[int] = None
    years_to_reach: Optional[int] = None


class RetirementEstimate(BaseModel):
    applicable: bool
    retirement_age: Optional[int] = None
    years_to_retirement: Optional[int] = None
    projected_corpus: Optional[float] = None
    sustainable_annual_income: Optional[float] = None
    sustainable_monthly_income: Optional[float] = None
    real_sustainable_monthly_income: Optional[float] = None


class TwinResult(BaseModel):
    scenario: ScenarioInput
    projection: list[YearProjection]
    final_net_worth: float
    final_real_net_worth: float
    total_contributed: float
    total_growth: float
    retirement: RetirementEstimate
    goals: list[GoalTimeline]


def _compound_year(corpus: Decimal, annual_contribution: Decimal, annual_return: float) -> Decimal:
    """Grow a portfolio one year with monthly contributions (end-of-month)."""
    monthly_rate = Decimal(str((1 + annual_return) ** (1 / 12) - 1))
    monthly_contribution = annual_contribution / Decimal("12.00")
    value = corpus
    zero = Decimal("0.00")
    for _ in range(12):
        value = max(zero, value * (Decimal("1.00") + monthly_rate) + monthly_contribution)
    return value


def simulate(params: ScenarioInput) -> TwinResult:
    """Run the full projection and return a structured, explainable result using Decimal math."""
    monthly_income = _to_decimal(params.monthly_income)
    monthly_expenses = _to_decimal(params.monthly_expenses)
    corpus = _to_decimal(params.current_savings)

    salary_growth = Decimal(str(params.salary_growth))
    expense_growth = Decimal(str(params.expense_growth))

    projection: list[YearProjection] = []
    total_contributed = Decimal("0.00")

    for y in range(1, params.years + 1):
        # Growth applies at the start of each year after year 1.
        if y > 1:
            monthly_income *= (Decimal("1.00") + salary_growth)
            monthly_expenses *= (Decimal("1.00") + expense_growth)

        annual_income = monthly_income * Decimal("12.00")
        annual_expenses = monthly_expenses * Decimal("12.00")
        annual_savings = annual_income - annual_expenses
        total_contributed += annual_savings

        corpus = _compound_year(corpus, annual_savings, params.investment_return)
        real_factor = (1 + params.inflation) ** y
        emergency_months = (float(corpus) / float(monthly_expenses)) if monthly_expenses > Decimal("0.00") else 0.0

        projection.append(
            YearProjection(
                year=y,
                age=(params.current_age + y) if params.current_age is not None else None,
                annual_income=_round_money(annual_income),
                annual_expenses=_round_money(annual_expenses),
                annual_savings=_round_money(annual_savings),
                invested=_round_money(corpus),
                net_worth=_round_money(corpus),
                real_net_worth=round(float(corpus) / real_factor, 2),
                emergency_fund_months=round(emergency_months, 1),
            )
        )

    final_net_worth = projection[-1].net_worth if projection else float(corpus)
    final_real = projection[-1].real_net_worth if projection else float(corpus)

    retirement = _retirement(params, projection)
    goals = _goals(params, projection)

    total_growth = final_net_worth - float(params.current_savings) - float(total_contributed)

    return TwinResult(
        scenario=params,
        projection=projection,
        final_net_worth=round(final_net_worth, 2),
        final_real_net_worth=round(final_real, 2),
        total_contributed=_round_money(total_contributed),
        total_growth=round(total_growth, 2),
        retirement=retirement,
        goals=goals,
    )



def _retirement(params: ScenarioInput, projection: list[YearProjection]) -> RetirementEstimate:
    if params.current_age is None or params.retirement_age is None:
        return RetirementEstimate(applicable=False)
    years_to = params.retirement_age - params.current_age
    if years_to <= 0 or not projection:
        return RetirementEstimate(applicable=False)

    # Use the projected corpus at (or nearest to) the retirement year.
    idx = min(years_to, len(projection)) - 1
    corpus = projection[idx].net_worth
    sustainable_annual = corpus * SAFE_WITHDRAWAL_RATE
    real_factor = (1 + params.inflation) ** (idx + 1)
    return RetirementEstimate(
        applicable=True,
        retirement_age=params.retirement_age,
        years_to_retirement=years_to,
        projected_corpus=round(corpus, 2),
        sustainable_annual_income=round(sustainable_annual, 2),
        sustainable_monthly_income=round(sustainable_annual / 12, 2),
        real_sustainable_monthly_income=round(sustainable_annual / 12 / real_factor, 2),
    )


def _goals(params: ScenarioInput, projection: list[YearProjection]) -> list[GoalTimeline]:
    out: list[GoalTimeline] = []
    for g in params.goals:
        reached_year = None
        for p in projection:
            if p.net_worth >= g.target_amount:
                reached_year = p.year
                break
        out.append(
            GoalTimeline(
                name=g.name,
                target_amount=g.target_amount,
                reached=reached_year is not None,
                year_reached=reached_year,
                years_to_reach=reached_year,
            )
        )
    return out


def defaults_from_result(result: dict) -> dict:
    """Sensible scenario defaults derived from the user's computed data."""
    hs = result.get("health_score", {}) or {}
    return {
        "monthly_income": float(hs.get("income", 0) or 0),
        "monthly_expenses": float(hs.get("expenses", 0) or 0),
        "current_savings": 0.0,
    }
