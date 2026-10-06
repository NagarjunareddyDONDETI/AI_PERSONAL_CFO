---
name: emergency-fund-audit
description: Evaluates emergency reserve adequacy and calculates runway gap.
version: 1.0.0
author: AI Personal CFO Team
category: risk
required_tools:
  - calculate_emergency_runway
  - plan_goal_contributions
required_data:
  - current_savings
  - monthly_expenses
safety_constraints:
  - Minimum safe emergency runway recommendation is 3-6 months of essential living expenses.
  - Do not recommend aggressive investing if emergency runway is under 3 months.
---

# Emergency Fund Audit Skill

Stress-test the user's liquid cash reserves against unexpected income disruption, medical emergencies, or urgent repairs.

## When to Use
- User asks "Is my emergency fund enough?" or "How many months of runway do I have?"
- Pre-flight check before recommending aggressive investment or debt payoff strategies.

## Prerequisites
- Current liquid savings / bank balances.
- Monthly essential living expenses.

## Deterministic Procedure
1. Call `calculate_emergency_runway(current_savings, monthly_expenses, target_months=6)`.
2. Determine exact months of coverage and funding gap shortfall.
3. If shortfall > 0, call `plan_goal_contributions` to compute monthly funding plan to reach target runway in 6-12 months.

## Output Format
- **Current Emergency Runway**: Exact months covered.
- **Target Reserve**: Calculated amount for 3-6 months coverage.
- **Shortfall / Surplus**: Exact currency difference.
- **Replenishment Plan**: Recommended monthly deposit to reach target.
