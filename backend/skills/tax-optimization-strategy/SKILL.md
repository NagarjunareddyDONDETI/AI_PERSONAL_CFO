---
name: tax-optimization-strategy
description: Identifies structured tax deductions and retirement exemptions.
version: 1.0.0
author: AI Personal CFO Team
category: tax
required_tools:
  - calculate_cashflow_summary
required_data:
  - annual_income
  - tax_bracket
safety_constraints:
  - Always include the mandatory disclaimer: "This is educational analysis, not certified professional tax advice."
  - Never fabricate non-existent deductions or guarantee tax refunds.
---

# Tax Optimization Strategy Skill

Examine annual income, retirement contributions, and eligible deductions to optimize after-tax net wealth.

## When to Use
- User asks "How can I reduce my tax liability?" or "What tax-saving investments make sense for my income?"
- Year-end tax planning discussions.

## Prerequisites
- Gross annual income and estimated current tax bracket.

## Deterministic Procedure
1. Calculate gross annual earnings baseline.
2. Determine statutory standard deductions and retirement account annual limits.
3. Quantify tax savings achievable through eligible retirement deposits, health insurance, and home loan interest exemptions.

## Output Format
- **Tax Bracket & Gross Income**: Current baseline.
- **Deduction Opportunities**: Eligible allowances and caps.
- **Potential Annual Tax Savings**: Estimated reduction in tax liability.
- **Compliance Disclaimer**: Prominently displayed.
