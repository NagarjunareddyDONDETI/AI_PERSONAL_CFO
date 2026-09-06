"""Anomaly detection.

Two deterministic checks:
1. Month-category totals more than 1.5 std deviations above that category's
   own historical monthly mean.
2. Single transactions that are both statistically unusual for this user and
   materially large relative to their monthly spending.

Check 2 deliberately requires two conditions. A mean-based threshold alone
misfires badly on high-volume, low-value statements: 160 UPI payments averaging
Rs.159 make any Rs.500 payment "3x the average", so ordinary spending gets
flagged. Since each anomaly costs 10 health-score points (capped at 30), noise
here directly misstates the headline score.
"""
from __future__ import annotations

import statistics
from collections import defaultdict

# Robust spread: scale MAD so it is comparable to a standard deviation.
_MAD_TO_SIGMA = 1.4826
# A flagged transaction must be at least this share of the month's expenses.
_MATERIALITY_SHARE = 0.05
# Cap the flags. The score penalty maxes out at 3 anomalies, so a longer list
# adds noise without changing the outcome.
_MAX_LARGE_FLAGS = 5


def _large_transaction_limit(expenses: list[float]) -> float:
    """A robust "unusually large for this user" threshold.

    Uses the median and median absolute deviation instead of the mean, so a long
    tail of small payments cannot drag the baseline down.
    """
    median = statistics.median(expenses)
    mad = statistics.median([abs(x - median) for x in expenses])
    robust_sigma = _MAD_TO_SIGMA * mad
    return max(3.0 * median, median + 4.0 * robust_sigma)


def detect_anomalies(categorized: list[dict], monthly_summary: dict) -> list[dict]:
    anomalies: list[dict] = []
    by_month_category = monthly_summary["by_month_category"]
    # Partial boundary months are not comparable to full ones, so they would
    # register as spikes or drops that never happened.
    months = monthly_summary.get("complete_months") or monthly_summary["months"]

    # --- Check 1: month-category totals vs category history ---
    # Build per-category series of monthly EXPENSE totals (positive numbers).
    category_series: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for month in months:
        for cat, total in by_month_category.get(month, {}).items():
            if cat == "Income":
                continue
            category_series[cat].append((month, abs(total)))

    for cat, series in category_series.items():
        values = [v for _, v in series]
        if len(values) < 2:
            continue
        mean = statistics.mean(values)
        std = statistics.pstdev(values)
        if std == 0:
            continue
        threshold = mean + 1.5 * std
        for month, value in series:
            if value > threshold:
                anomalies.append(
                    {
                        "type": "category_spike",
                        "month": month,
                        "category": cat,
                        "amount": round(value, 2),
                        "expected": round(mean, 2),
                        "severity": "high" if value > mean + 3 * std else "medium",
                        "message": (
                            f"{cat} spending in {month} was Rs.{value:,.0f}, "
                            f"well above your usual Rs.{mean:,.0f}."
                        ),
                    }
                )

    # --- Check 2: single transactions that are unusual AND material ---
    expenses = [abs(t["amount"]) for t in categorized if t["amount"] < 0]
    if expenses:
        limit = _large_transaction_limit(expenses)
        typical = statistics.median(expenses)
        monthly_expenses = monthly_summary.get("monthly_expenses", {})
        # Fallback for a single-month statement.
        avg_month_expense = (
            sum(monthly_expenses.values()) / len(monthly_expenses)
            if monthly_expenses
            else sum(expenses)
        )

        candidates = []
        for txn in categorized:
            if txn["amount"] >= 0:
                continue
            amount = abs(txn["amount"])
            if amount <= limit:
                continue
            # Materiality: a payment worth a couple of percent of the month is
            # not news, however far it sits from the median.
            month_total = monthly_expenses.get(txn["date"][:7]) or avg_month_expense
            if month_total > 0 and amount < _MATERIALITY_SHARE * month_total:
                continue
            candidates.append((amount, txn))

        # Report the biggest ones; they are the only ones worth acting on.
        candidates.sort(key=lambda pair: pair[0], reverse=True)
        for amount, txn in candidates[:_MAX_LARGE_FLAGS]:
            share = amount / (monthly_expenses.get(txn["date"][:7]) or avg_month_expense or 1)
            anomalies.append(
                {
                    "type": "large_transaction",
                    "date": txn["date"],
                    "category": txn["category"],
                    "description": txn["description"],
                    "amount": round(amount, 2),
                    "expected": round(typical, 2),
                    "severity": "high" if share >= 0.15 else "medium",
                    "message": (
                        f"Large transaction on {txn['date']}: "
                        f"{txn['description']} for Rs.{amount:,.0f} — "
                        f"{share:.0%} of that month's spending "
                        f"(typical payment is Rs.{typical:,.0f})."
                    ),
                }
            )

    return anomalies
