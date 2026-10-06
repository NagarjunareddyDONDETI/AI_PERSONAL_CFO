---
name: budget-analysis
description: Audits income vs expenses against the 50/30/20 budget framework.
version: 1.0.0
author: AI Personal CFO Team
category: budgeting
required_tools:
  - calculate_cashflow_summary
required_data:
  - monthly_income
  - monthly_expenses
  - category_totals
safety_constraints:
  - Never estimate or guess user income or expenses without deterministic tool output.
  - Highlight essential needs vs discretionary wants objectively.
---

# Budget Analysis Skill

Analyze user spending patterns to determine budget health, surplus generation, and compliance with the 50/30/20 guideline (50% Needs, 30% Wants, 20% Savings).

## When to Use
- User asks about their monthly budget balance, spending distribution, or where money went.
- Evaluating whether a user has sufficient monthly surplus to allocate to new goals.

## Prerequisites
- Verified monthly income and expense totals from processed bank statements or user profile.
- Category-level breakdown of transactions.

## Deterministic Procedure
1. Execute `calculate_cashflow_summary(income, expenses)` to establish exact net surplus, savings rate, and burn ratio.
2. Group category totals into Needs (Housing, Utilities, Groceries, Healthcare, Debt Minimums) and Wants (Dining, Shopping, Entertainment, Subscriptions).
3. Compute Needs %, Wants %, and Savings % strictly using computed values.
4. Compare against 50/30/20 benchmarks.

## Output Format
- **Monthly Income & Expenses**: Exact totals.
- **Net Cash Flow**: Surplus (+) or Deficit (-).
- **50/30/20 Allocation**: Needs %, Wants %, Savings %.
- **Actionable Steps**: 2-3 specific category adjustments based on biggest discretionary outflows.

## Safety Constraints
- All percentage calculations must be derived from `calculate_cashflow_summary`.
- Do not fabricate missing category totals.
