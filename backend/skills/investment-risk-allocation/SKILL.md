---
name: investment-risk-allocation
description: Evaluates risk tolerance and projects compound wealth growth.
version: 1.0.0
author: AI Personal CFO Team
category: investment
required_tools:
  - calculate_compound_growth
  - calculate_emergency_runway
required_data:
  - monthly_surplus
  - current_savings
  - monthly_expenses
  - risk_profile
safety_constraints:
  - Confirm minimum 3 months emergency buffer before deploying surplus to market investments.
  - State clearly that historical market returns do not guarantee future performance.
---

# Investment Risk & Allocation Skill

Determine investment readiness and simulate wealth accumulation based on the user's risk profile, surplus capacity, and investment horizon.

## When to Use
- User asks "How much should I invest every month?" or "Where will my investments be in 10 years?"
- User wants to explore equity vs debt allocation suitable for their timeline.

## Prerequisites
- Monthly investable surplus.
- Emergency reserve status.
- Time horizon and risk profile (Conservative, Moderate, Aggressive).

## Deterministic Procedure
1. Verify liquidity safety via `calculate_emergency_runway`.
2. Map risk profile to expected long-term return rate (e.g., Conservative ~6%, Moderate ~9%, Aggressive ~12%).
3. Call `calculate_compound_growth(principal, monthly_contribution, annual_rate_pct, years)`.

## Output Format
- **Investment Readiness Check**: Safety net verified.
- **Recommended Allocation**: Broad asset allocation bands.
- **Projected Future Value**: Total invested capital vs accumulated compound returns.
- **Milestone Timeline**: Estimated years to double portfolio or reach targets.
