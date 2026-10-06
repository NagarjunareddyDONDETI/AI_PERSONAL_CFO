---
name: lifestyle-creep-detector
description: Identifies discretionary spending growth that outpaces income.
version: 1.0.0
author: AI Personal CFO Team
category: lifestyle
required_tools:
  - calculate_cashflow_summary
  - detect_anomalies
required_data:
  - monthly_summary
  - transactions
safety_constraints:
  - Distinguish genuine inflation in essential goods from lifestyle creep in luxury/discretionary categories.
---

# Lifestyle Creep Detector Skill

Detect stealth increases in discretionary spending (dining out, travel, premium subscriptions, impulse shopping) that erode savings potential as income rises.

## When to Use
- User wonders why their savings aren't increasing despite salary raises.
- Periodic quarterly expenditure audit.

## Prerequisites
- Multi-month transaction records and category spending trends.

## Deterministic Procedure
1. Call `detect_anomalies` on transaction batches to uncover recurring spending spikes.
2. Calculate discretionary category trends across months.
3. Compare rate of discretionary spending growth against income growth.

## Output Format
- **Discretionary Spending Trend**: Category-by-category changes.
- **Top Leakage Categories**: Specific areas where spending inflated.
- **Monthly Savings Opportunity**: Amount recoverable by capping discretionary creep.
