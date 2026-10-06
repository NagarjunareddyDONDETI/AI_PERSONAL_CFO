# FINZO Model Context Protocol (MCP) Server Guide

The FINZO MCP Server exposes the platform's deterministic financial calculation engine to external autonomous agents (such as **NousResearch Hermes Agent**, **Claude Desktop**, or any standard MCP client).

---

## 1. Capabilities & Guarantees

- **Zero LLM Math Hallucinations**: All mathematical operations, debt amortization, compound interest, emergency runways, and health scores are computed with pure Python `Decimal` arithmetic.
- **Protocol**: Compliant with JSON-RPC 2.0 / MCP Protocol (Version `2024-11-05`).
- **Transport**: Standard I/O (`stdio`) or embedded process.

---

## 2. Running the MCP Server

```bash
# Set PYTHONPATH to backend directory
cd backend
python -m mcp_server.server
```

---

## 3. Connecting to Claude Desktop / Cursor / Hermes Agent

### Claude Desktop Configuration (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "finzo-cfo": {
      "command": "python",
      "args": [
        "-m",
        "mcp_server.server"
      ],
      "cwd": "C:\\Users\\D NAGARJUNA\\AI_PERSONAL_CFO\\backend",
      "env": {
        "PYTHONPATH": "C:\\Users\\D NAGARJUNA\\AI_PERSONAL_CFO\\backend"
      }
    }
  }
}
```

### Hermes Agent Integration

Hermes Agent connects via standard MCP JSON-RPC stdio. When configured, Hermes can query FINZO's deterministic financial tools:
- `calculate_cashflow_summary`
- `calculate_emergency_runway`
- `calculate_debt_metrics`
- `calculate_debt_payoff_timeline`
- `calculate_compound_growth`
- `plan_goal_contributions`
- `calculate_health_score`
- `detect_anomalies`

---

## 4. MCP Tools Reference

| Tool Name | Parameters | Returns |
| :--- | :--- | :--- |
| `calculate_cashflow_summary` | `income`, `expenses` | `monthly_income`, `monthly_expenses`, `net_surplus`, `savings_rate_pct`, `burn_ratio_pct`, `is_cashflow_positive` |
| `calculate_emergency_runway` | `current_savings`, `monthly_expenses`, `target_months` | `runway_months`, `target_months`, `target_amount`, `savings_gap`, `is_adequately_funded`, `status` |
| `calculate_debt_metrics` | `monthly_income`, `debts` | `total_debt_balance`, `total_monthly_debt_payments`, `dti_percentage`, `risk_level` |
| `calculate_debt_payoff_timeline` | `debts`, `extra_monthly_payment`, `strategy` | `strategy`, `total_months_to_debt_free`, `total_interest_paid`, `total_interest_saved`, `schedule` |
| `calculate_compound_growth` | `principal`, `monthly_contribution`, `annual_rate_pct`, `years` | `future_value`, `total_contributions`, `total_interest_earned`, `yearly_breakdown` |
| `plan_goal_contributions` | `target_amount`, `current_saved`, `target_months`, `expected_annual_return_pct` | `required_monthly_savings`, `target_amount`, `target_months`, `is_achievable` |
| `calculate_health_score` | `income`, `expenses`, `anomalies_count`, `emergency_fund_months`, `active_emis` | `score`, `rating`, `component_breakdown`, `penalties` |
| `detect_anomalies` | `transactions`, `iqr_multiplier` | `anomalies`, `anomalies_count`, `total_anomaly_spend`, `outlier_threshold` |
