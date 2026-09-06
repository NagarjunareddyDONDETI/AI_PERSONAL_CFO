"""Forecasting via LinearRegression on monthly totals.

Predicts next month's total expenses and the next-month total for each of the
top categories. Falls back to a simple average when there is too little data
to fit a regression.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LinearRegression


def _predict_series(values: list[float]) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    if n < 2:
        return round(values[-1], 2)
    X = np.arange(n).reshape(-1, 1)
    y = np.array(values)
    model = LinearRegression().fit(X, y)
    pred = float(model.predict([[n]])[0])
    return round(max(0.0, pred), 2)


def forecast_next_month(monthly_summary: dict, top_n: int = 4) -> dict:
    # Fit on complete months only. A partial trailing month (a statement ending
    # on the 1st) drags the regression into a steep decline, and clamping the
    # negative prediction at zero is what produced a forecast of exactly 0.
    months = monthly_summary.get("complete_months") or monthly_summary["months"]
    monthly_expenses = monthly_summary["monthly_expenses"]

    expense_series = [monthly_expenses.get(m, 0.0) for m in months]
    total_forecast = _predict_series(expense_series)

    # Per-category forecast for the top categories by total spend.
    category_totals = monthly_summary["category_totals"]
    top_categories = sorted(category_totals, key=category_totals.get, reverse=True)[:top_n]

    by_month_category = monthly_summary["by_month_category"]
    category_forecast: dict[str, float] = {}
    for cat in top_categories:
        series = [abs(by_month_category.get(m, {}).get(cat, 0.0)) for m in months]
        category_forecast[cat] = _predict_series(series)

    # Forecast the month after the last month we actually modelled, so the label
    # matches the data behind it.
    next_month_label = _next_month_label(months[-1]) if months else None

    return {
        "next_month": next_month_label,
        "total_expense_forecast": total_forecast,
        "category_forecast": category_forecast,
        "history": {"months": months, "expenses": expense_series},
    }


def _next_month_label(last_month: str) -> str:
    year, month = map(int, last_month.split("-"))
    month += 1
    if month > 12:
        month = 1
        year += 1
    return f"{year:04d}-{month:02d}"
