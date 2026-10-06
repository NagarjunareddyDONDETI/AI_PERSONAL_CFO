---
name: goal-feasibility-planner
description: Computes required monthly savings and deadlines for milestones.
version: 1.0.0
author: AI Personal CFO Team
category: goals
required_tools:
  - plan_goal_contributions
  - calculate_cashflow_summary
required_data:
  - target_amount
  - current_saved
  - target_months
  - monthly_surplus
safety_constraints:
  - Do not mark a goal as feasible if required monthly savings exceeds available net monthly surplus.
---

# Goal Feasibility Planner Skill

Quantify whether a major financial milestone (down payment, education, car, wedding, retirement) is realistically achievable under current cashflow constraints.

## When to Use
- User asks "Can I buy a house in 5 years?" or "How much do I need to save each month for a $50,000 wedding in 2 years?"
- Setting up new financial goals in the CFO dashboard.

## Prerequisites
- Target goal amount.
- Existing savings earmarked for the goal.
- Desired timeline in months.
- User's current monthly net surplus.

## Deterministic Procedure
1. Call `plan_goal_contributions(target_amount, current_saved, target_months, expected_annual_return_pct)`.
2. Compare required monthly savings against available net cashflow surplus from `calculate_cashflow_summary`.
3. If required monthly savings > surplus, compute the realistic extended deadline or required discretionary spending reduction.

## Output Format
- **Goal Objective**: Target amount and deadline.
- **Required Monthly Savings**: Exact computed figure.
- **Feasibility Assessment**: Feasible (Surplus > Required) or Deficit (Surplus < Required).
- **Optimization Strategy**: Tradeoff recommendations if cashflow is currently insufficient.
