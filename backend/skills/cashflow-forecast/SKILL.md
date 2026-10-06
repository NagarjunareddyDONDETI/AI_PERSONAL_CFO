---
name: cashflow-forecast
description: Projects near-term liquidity and identifies cash deficit risks.
version: 1.0.0
author: AI Personal CFO Team
category: forecasting
required_tools:
  - calculate_cashflow_summary
required_data:
  - monthly_income
  - monthly_expenses
  - recurring_commitments
safety_constraints:
  - Do not extrapolate non-recurring one-off spikes as permanent monthly burn.
  - Require explicit baseline numbers for forward projections.
---

# Cashflow Forecast Skill

Project monthly cash flows over upcoming quarters, identify seasonal variance, and evaluate liquidity buffers against upcoming commitments.

## When to Use
- User asks "Will I run out of money in 3 months?" or "How will my cash flow look next quarter?"
- User is planning a major expenditure and wants to verify liquidity safety.

## Prerequisites
- Historical monthly income and expenses across at least 2 consecutive months.
- List of scheduled recurring commitments (rent, insurance, subscriptions, EMIs).

## Deterministic Procedure
1. Call `calculate_cashflow_summary` to establish baseline net monthly cashflow.
2. Overlay known fixed recurring commitments to determine non-discretionary baseline floor.
3. Compute 3-month and 6-month cumulative liquidity trajectory.
4. Flag any month where cumulative cash buffer falls below 1 month of living expenses.

## Output Format
- **Baseline Net Monthly Cash Flow**: Currency value and direction.
- **Fixed vs Discretionary Ratio**: Percentage breakdown.
- **Liquidity Runway Projection**: Estimated cash reserves at +3, +6, and +12 months.
- **Risk Assessment**: Safe, Tight, or Deficit Risk.
