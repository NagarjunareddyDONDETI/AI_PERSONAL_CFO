---
name: financial-health-assessment
description: Generates a comprehensive 0-100 financial health scorecard.
version: 1.0.0
author: AI Personal CFO Team
category: health
required_tools:
  - calculate_health_score
required_data:
  - income
  - expenses
  - anomalies_count
  - emergency_fund_months
  - active_emis
safety_constraints:
  - Health score is computed strictly by the deterministic formula (100 baseline minus weighted penalties).
  - LLM must only narrate and explain the component penalties.
---

# Financial Health Assessment Skill

Evaluate an individual's complete financial resilience, liquidity, debt burden, and savings discipline in a single unified score from 0 to 100.

## When to Use
- User asks "What is my financial health score?" or "How financially healthy am I?"
- Monthly periodic financial reviews.

## Prerequisites
- Monthly income and expenses.
- Count of detected spending anomalies.
- Emergency reserve depth.
- Count of active EMIs.

## Deterministic Procedure
1. Call `calculate_health_score(income, expenses, anomalies_count, emergency_fund_months, active_emis)`.
2. Inspect itemized penalties (savings rate penalty, emergency fund penalty, anomaly penalty, EMI penalty).
3. Identify the single largest drag on the user's score.

## Output Format
- **Overall Health Score**: 0-100 score and rating category (Healthy, Moderate, Needs Attention).
- **Key Metrics**: Savings Rate %, Emergency Months, Active EMIs, Anomalies.
- **Score Breakdown**: Itemized penalties subtracted from 100.
- **Actionable Prescription**: Top priority action to gain the most points.
