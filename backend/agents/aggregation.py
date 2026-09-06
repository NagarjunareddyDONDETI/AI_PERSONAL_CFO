"""Monthly aggregation: group transactions by month and category.

Also classifies each month as complete or partial. A statement almost always
starts and ends mid-month, and treating a stub month as a full one badly distorts
everything downstream: the health score gets computed from a day or two of data,
and the expense forecast fits a cliff-edge slope through it.
"""
from __future__ import annotations

import calendar
import statistics
from collections import defaultdict


def _month_key(date: str) -> str:
    # date is ISO "YYYY-MM-DD"
    return date[:7]  # "YYYY-MM"


# A boundary month is only called partial when calendar coverage AND activity
# both look short. Requiring two independent signals avoids misjudging a month
# that is fully covered but genuinely quiet.
_COVERAGE_THRESHOLD = 0.5
_ACTIVITY_THRESHOLD = 0.5


def _days_in_month(month: str) -> int:
    year, mon = int(month[:4]), int(month[5:7])
    return calendar.monthrange(year, mon)[1]


def _find_partial_months(
    months: list[str],
    first_day: dict[str, int],
    last_day: dict[str, int],
    activity: dict[str, float],
) -> list[str]:
    """Identify boundary months that only cover part of their calendar month.

    Only the first and last months can be partial — a month in the middle of a
    statement is covered by definition. Never returns every month, since scoring
    needs at least one reference period.
    """
    if len(months) < 2:
        return []

    others = [activity[m] for m in months[1:-1]] or [
        activity[m] for m in months if m not in (months[0], months[-1])
    ]
    partial: list[str] = []

    def _median_excluding(target: str) -> float:
        rest = [activity[m] for m in months if m != target]
        return statistics.median(rest) if rest else 0.0

    # Trailing month: does the data stop well before the month does?
    last = months[-1]
    med = _median_excluding(last)
    coverage = last_day[last] / _days_in_month(last)
    if coverage < _COVERAGE_THRESHOLD and (
        med <= 0 or activity[last] < _ACTIVITY_THRESHOLD * med
    ):
        partial.append(last)

    # Leading month: does the data start well after the month does?
    first = months[0]
    med = _median_excluding(first)
    remaining = _days_in_month(first) - first_day[first] + 1
    if remaining / _days_in_month(first) < _COVERAGE_THRESHOLD and (
        med <= 0 or activity[first] < _ACTIVITY_THRESHOLD * med
    ):
        partial.append(first)

    # Never mark everything partial.
    if len(partial) >= len(months):
        partial = partial[:-1]
    return sorted(partial)


def aggregate_monthly(categorized: list[dict]) -> dict:
    """Produce a monthly summary.

    Returns:
        {
          "months": ["2025-01", ...],
          "by_month_category": { "2025-01": { "Food": 1234.0, ... }, ... },
          "monthly_income": { "2025-01": 85000.0, ... },
          "monthly_expenses": { "2025-01": 40000.0, ... },
          "category_totals": { "Food": 5000.0, ... },   # expenses only
          "partial_months": ["2026-09"],   # only cover part of the calendar month
          "complete_months": ["2026-08"],  # safe to score and forecast on
        }
    """
    by_month_category: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    monthly_income: dict[str, float] = defaultdict(float)
    monthly_expenses: dict[str, float] = defaultdict(float)
    category_totals: dict[str, float] = defaultdict(float)
    first_day: dict[str, int] = {}
    last_day: dict[str, int] = {}

    for txn in categorized:
        month = _month_key(txn["date"])
        cat = txn["category"]
        amt = txn["amount"]
        by_month_category[month][cat] += amt
        if amt > 0 or cat == "Income":
            monthly_income[month] += amt
        else:
            spend = abs(amt)
            monthly_expenses[month] += spend
            category_totals[cat] += spend

        try:
            day = int(txn["date"][8:10])
        except (ValueError, TypeError, IndexError):
            day = 1
        first_day[month] = min(first_day.get(month, day), day)
        last_day[month] = max(last_day.get(month, day), day)

    months = sorted(by_month_category.keys())
    activity = {
        m: monthly_income[m] + monthly_expenses[m] for m in months
    }
    partial = _find_partial_months(months, first_day, last_day, activity)

    return {
        "months": months,
        "by_month_category": {m: dict(by_month_category[m]) for m in months},
        "monthly_income": {m: round(monthly_income[m], 2) for m in months},
        "monthly_expenses": {m: round(monthly_expenses[m], 2) for m in months},
        "category_totals": {k: round(v, 2) for k, v in category_totals.items()},
        "partial_months": partial,
        "complete_months": [m for m in months if m not in partial],
    }
