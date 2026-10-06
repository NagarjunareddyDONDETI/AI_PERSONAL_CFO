---
name: debt-payoff-optimizer
description: Optimizes debt amortization via Avalanche and Snowball strategies.
version: 1.0.0
author: AI Personal CFO Team
category: debt
required_tools:
  - calculate_debt_metrics
  - calculate_debt_payoff_timeline
required_data:
  - monthly_income
  - debts
safety_constraints:
  - Minimum monthly payments on all active debts must always be satisfied before allocating extra funds.
  - Never fabricate interest rates or balances.
---

# Debt Payoff Optimizer Skill

Compare Debt Avalanche (highest interest rate first — mathematically optimal) vs Debt Snowball (lowest balance first — behavioral momentum) to eliminate debt fast.

## When to Use
- User has credit card debt, personal loans, student loans, or vehicle EMIs and asks how to become debt-free.
- User wants to know which loan to pay off first with extra monthly surplus.

## Prerequisites
- List of debts: Name, Balance, Monthly Payment (EMI), Annual Interest Rate (APR).
- Available monthly extra payment beyond minimums.

## Deterministic Procedure
1. Call `calculate_debt_metrics(monthly_income, debts)` to compute overall DTI and total interest burden.
2. Call `calculate_debt_payoff_timeline(debts, extra_monthly, strategy="avalanche")`.
3. Call `calculate_debt_payoff_timeline(debts, extra_monthly, strategy="snowball")`.
4. Contrast total interest paid and payoff date between both methods.

## Output Format
- **Current Debt Overview**: Total balance, total monthly payments, DTI %.
- **Avalanche Strategy**: Months to freedom, total interest paid.
- **Snowball Strategy**: Months to freedom, total interest paid.
- **Recommendation**: Priority ordering of loans to attack first.
