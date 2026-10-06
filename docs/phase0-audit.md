# Phase 0 Audit: AI Personal CFO (FINZO) Architecture, Math, Security, and RAGFlow Integration

**Date**: 2026-10-06  
**Auditor**: Senior AI Systems Architect & Production Engineer  
**Status**: Ready for User Review (STOP & WAIT FOR APPROVAL)

---

## 1. Repository Map & How to Run

### 1.1 Project Structure Overview
```
AI_PERSONAL_CFO/
├── backend/
│   ├── main.py                     # FastAPI application entrypoint, routes, middleware, and endpoints
│   ├── requirements.txt            # Python dependencies (FastAPI, LangGraph, scikit-learn, SymPy, pdfplumber, ChromaDB)
│   ├── orchestrator/
│   │   ├── pipeline.py             # LangGraph stateful workflow orchestrator
│   │   └── intent_router.py        # Deterministic query intent classifier
│   ├── agents/
│   │   ├── ingestion_agent.py      # Multi-format statement parser (CSV, PDF, Excel)
│   │   ├── categorization.py       # Deterministic keyword categorization + LLM fallback
│   │   ├── aggregation.py          # Monthly summary and category rollups
│   │   ├── anomaly.py              # Statistical anomaly detector (IQR on spending distributions)
│   │   ├── forecasting.py          # Expense trend forecasting (scikit-learn LinearRegression)
│   │   ├── health_score.py         # Deterministic financial health scoring engine (0-100)
│   │   ├── savings_advisor.py      # Rule-based spending reduction suggestions
│   │   ├── copilot.py              # Multi-turn memory-grounded CFO conversational copilot
│   │   ├── explainer.py            # Grounded single-turn explanation engine
│   │   ├── whatif.py               # Deterministic purchase simulator (Full payment vs EMI)
│   │   ├── twin.py                 # Digital Financial Twin simulation engine (multi-year projection)
│   │   ├── memory.py               # Per-user structured SQLite memory + ChromaDB vector recall
│   │   ├── rag.py                  # Financial knowledge retrieval and context grounding
│   │   ├── llm_client.py           # Multi-provider LLM client (Gemini 2.5/Flash, etc.)
│   │   └── debate/
│   │       ├── specialists.py      # 8 specialist agents (Risk, Savings, Investment, Lifestyle, Budget, Debt, Tax, Planner)
│   │       └── decider.py          # Decision Agent chair synthesizing specialist consensus & trade-offs
│   ├── tools/
│   │   ├── financial_tools.py      # Pure deterministic financial math engine
│   │   └── registry.py             # Central tool registry with OpenAI tool schemas & validation
│   ├── skills/
│   │   ├── skill_registry.py       # Parser and loader for standardized financial skills
│   │   └── */SKILL.md              # Skill definitions (audit, runway, debt payoff, goal planning)
│   ├── cron/
│   │   ├── monitors.py             # Autonomous sentinels (daily anomaly, weekly budget pulse, monthly CFO report)
│   │   └── scheduler.py            # Resilient background thread scheduler
│   ├── db/
│   │   └── database.py             # SQLite persistence layer (transactions, twin, goals, audit log, memory)
│   └── tests/
│       ├── test_deterministic_tools.py
│       ├── test_financial_safety_adversarial.py
│       ├── test_cfo_memory.py
│       ├── test_autonomous_monitors.py
│       └── ... (445 passing tests)
├── frontend/
│   ├── index.html
│   ├── package.json                # React 18, Vite, TailwindCSS, Framer Motion, Lucide icons
│   ├── vite.config.ts
│   └── src/
│       ├── App.tsx                 # Main layout with tabbed navigation and real-time state
│       ├── api.ts                  # Typed frontend API client connecting to FastAPI
│       └── components/             # Glassmorphic UI components (MemoryPanel, TwinSimulation, WhatIf, etc.)
└── docs/
    └── phase0-audit.md             # This audit document
```

### 1.2 How to Run Backend & Frontend

#### Backend
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
# Run FastAPI server on port 8000
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

#### Frontend
```bash
cd frontend
npm install
npm run dev
# Access UI at http://localhost:5173
```

#### Running Tests
```bash
cd backend
pytest -v
# Output: 445 passed in ~25s
```

---

## 2. Component Table & Quality Verdict

| Component | Status | File Paths | Quality Notes | Verdict & Justification |
| :--- | :--- | :--- | :--- | :--- |
| **Ingestion Pipeline** | Exists | `backend/agents/ingestion_agent.py` | Parses CSV, PDF (`pdfplumber`), Excel (`openpyxl`). Extracts tabular rows into standard transaction dictionaries. | **Modify**: Wrap with `DocumentParser` interface. Retain existing parser as `LocalParser` (default). Add optional `RagflowParser` alongside it for DeepDoc layout parsing with a deterministic validation gate. |
| **Transaction Schema / DB** | Exists | `backend/db/database.py` | SQLite schema storing `results`, `twin_scenarios`, `goals`, `memories`, `audit_log`, `agent_evaluations`. Parameterized queries, indexed foreign keys. | **Reuse & Extend**: Keep SQLite for local zero-config execution; prepare seamless PostgreSQL connection pooling via standard environment variables (`DATABASE_URL`). Add strict `Decimal` validation. |
| **RAG / Embeddings / Vector Store** | Exists | `backend/agents/rag.py`, `backend/agents/memory.py` | ChromaDB vector store with sentence-transformers or Gemini embeddings. Used for financial knowledge and user memory recall. | **Modify**: Isolate behind `KnowledgeRetriever` interface. Retain local ChromaDB and `NullKnowledgeBase` for 100% offline functionality; add `RagflowKnowledgeBase` as optional retrieval backend for citations. |
| **LangGraph Orchestrator** | Exists | `backend/orchestrator/pipeline.py` | Stateful DAG executing `ingestion -> categorization -> aggregation -> anomaly -> forecast -> health_score -> savings`. | **Reuse**: Keep existing LangGraph workflow as the primary orchestrator. Add an optional knowledge enrichment node without altering deterministic stages. |
| **Specialist Agents** | Exists | `backend/agents/debate/specialists.py` | 8 data-grounded specialists (Risk, Savings, Investment, Lifestyle, Budget, Debt, Tax, Planner). Each computes a stance from structured data before generating narrative. | **Reuse**: Specialized prompts and bounded scopes prevent domain cross-contamination. |
| **Decision Agent** | Exists | `backend/agents/debate/decider.py` | Synthesizes 8 specialist outputs, calculates consensus scores, and identifies trade-offs without recalculating financial figures. | **Reuse**: Ensures explainable multi-agent consensus. |
| **Financial Tools** | Exists | `backend/tools/financial_tools.py`, `backend/tools/registry.py` | Pure Python calculations for cashflow, runway, debt avalanche/snowball, compound growth, and health scoring. | **Modify & Harden**: Enforce `Decimal` arithmetic across all monetary fields to prevent floating-point inaccuracies. Expose tools via FastMCP server. |
| **Financial Twin** | Exists | `backend/agents/twin.py`, `backend/db/database.py` | Deterministic multi-year simulation engine projecting salary, expenses, inflation, investment compounding, and retirement runway. | **Reuse**: 100% mathematical, zero LLM reliance. |
| **Categorized Memory** | Exists | `backend/agents/memory.py`, `frontend/src/components/MemoryPanel.tsx` | 13 structured memory categories in SQLite with async ChromaDB vector embeddings. | **Reuse**: Fully user-isolated and durable. |
| **Voice Interface** | Exists | `backend/main.py` (`/voice/stream`), `frontend/src/components/VoiceOrb.tsx` | Streaming voice endpoint sharing the exact same intent routing and prompt preparation as the copilot. | **Reuse**: Thin adapter pattern already implemented. |
| **Auth & Rate Limiting** | Partial | `backend/main.py` | Header-based `X-User-ID` with token verification placeholder and in-memory rate limiter. | **Modify**: Implement robust JWT/OAuth verification and per-user row-level data isolation. |
| **Audit Logging** | Exists | `backend/db/database.py` (`log_audit_event`) | Structured database logging of execution timestamps, actions, user IDs, and metadata. | **Reuse & Extend**: Add automatic PII masking for transaction details and logs. |
| **Test Suite** | Exists | `backend/tests/` | 445 unit and integration tests covering math safety, adversarial inputs, memory, and autonomous sentinels. | **Reuse & Extend**: Add test suites for Decimal precision, parser adapters, and MCP server endpoints. |

---

## 3. Math & Calculation Safety Audit

### 3.1 Non-Negotiable Principle: Zero LLM Numerical Computation
We audited every module in the codebase where an LLM is called or where mathematical figures are handled:

1. **`agents/categorization.py`**:
   - *LLM role*: Suggests merchant category labels (e.g. `"Food"`, `"Shopping"`).
   - *Math risk*: **NONE**. Does not touch transaction amounts, dates, or balances.

2. **`agents/health_score.py` & `tools/financial_tools.py`**:
   - *Math engine*: Pure deterministic Python code. Formulas use explicit weights, threshold subtractions, and division-by-zero guards.
   - *LLM role*: **ZERO**. LLM is never invoked in health score or tool calculations.

3. **`agents/forecasting.py`**:
   - *Math engine*: `scikit-learn.linear_model.LinearRegression` fitted on complete historical calendar months. Clamped to `max(0.0, prediction)`.
   - *LLM role*: **ZERO**.

4. **`agents/whatif.py` & `agents/twin.py`**:
   - *Math engine*: Explicit compound interest, flat EMI calculations, and multi-year projection loops.
   - *LLM role*: **ZERO**.

5. **`agents/copilot.py` & `agents/explainer.py`**:
   - *LLM role*: Explains and narrates precomputed data slices.
   - *Safety Guard*: Strict system prompt constraint:
     ```
     STRICT RULES:
     - Use ONLY the numbers in "Computed financial data" below. Never invent, guess,
       or recompute financial figures. If a number is not present, say you don't have it.
     ```
   - *Fallback*: If LLM API key is missing or calls fail, deterministic templated strings are returned directly.

6. **Action Item for Phase 1**: Upgrade all monetary representations from `float` to Python's `Decimal` module in `tools/financial_tools.py` and `agents/` to eliminate floating-point rounding artifacts.

---

## 4. Security & Isolation Audit

1. **Authentication & Multi-Tenant Isolation**:
   - Current: Requests pass `X-User-ID` header; defaults to `"default_user"` for local standalone usage.
   - DB Isolation: All queries for results, memories, twin scenarios, and goals filter strictly by `WHERE user_id = ?`.
   - Enhancement: Add Bearer token authentication middleware with validated user identity context.

2. **Document Boundary & Prompt Injection Defense**:
   - Ingestion: Uploaded statements (PDF, CSV, Excel) are parsed into structured row objects `{"date", "amount", "description"}`.
   - **Crucial Rule**: Document text is never injected as instructions to an agent. Raw transaction descriptions are treated strictly as untrusted string literals for keyword matching and aggregation.

3. **Tool Execution Authorization**:
   - All deterministic tools in `backend/tools/registry.py` are pure computational functions.
   - Tools have no access to shell commands, filesystem deletion, or external network execution.

4. **Sensitive Data in Logs**:
   - Audit logs record event types and timestamps. Account numbers and PII in statement headers are ignored by local parsers.
   - Logging redaction will be enforced in Phase 6.

---

## 5. RAGFlow API Reference & Integration Specification

### 5.1 RAGFlow Architecture Role
- RAGFlow is an **OPTIONAL** ingestion and knowledge retrieval service.
- **NEVER** a source of financial truth or calculations.
- System operates at 100% functionality with `DOCUMENT_PARSER=local` and `KNOWLEDGE_RETRIEVER=null` when RAGFlow is absent.

### 5.2 RAGFlow API Endpoints to Integrate

Based on RAGFlow REST API v0.16+:

| Endpoint | Method | Purpose in AI Personal CFO | Fallback if Unavailable |
| :--- | :--- | :--- | :--- |
| `/api/v1/datasets` | `POST` / `GET` | Create/locate knowledge base dataset for financial guidelines & tax policies | In-memory / local knowledge dictionary |
| `/api/v1/datasets/{dataset_id}/documents` | `POST` | Upload PDF statement for DeepDoc layout parsing | `LocalParser` (`pdfplumber` / `openpyxl`) |
| `/api/v1/datasets/{dataset_id}/documents/{document_id}/parse` | `POST` | Trigger OCR & table extraction on uploaded document | Local regex and tabular parser |
| `/api/v1/datasets/{dataset_id}/documents/{document_id}` | `GET` | Poll parsing completion status | Synchronous timeout fallback to local parsing |
| `/api/v1/retrieval` | `POST` | Hybrid vector + keyword search for regulatory / tax explanations & citations | `NullKnowledgeBase` (returns empty citations with computed data) |

### 5.3 Ambiguities & Defensive Engineering
1. **Asynchronous Parsing Latency**: RAGFlow document parsing takes 5–30 seconds.
   - *Design*: The `RagflowParser` adapter will implement a configurable timeout (e.g., 10s). If parsing times out or fails, it automatically falls back to `LocalParser` without crashing the user session.
2. **Table Extraction Fidelity**:
   - *Design*: All parsed rows returned by RAGFlow pass through a **Deterministic Validation Gate** before database entry:
     - `date`: Validated ISO format (`YYYY-MM-DD`).
     - `amount`: Converted to `Decimal`; non-zero.
     - `description`: Sanitized string, max length 256.
     - Malformed rows are discarded or flagged as unparsed.

---

## 6. Phased Implementation Plan

### Phase 1: Decimal Precision & Strict Financial Math Hardening
- **Goal**: Convert all monetary calculations from `float` to `Decimal` across `tools/financial_tools.py`, `agents/health_score.py`, `agents/whatif.py`, and `agents/twin.py`.
- **Files Touched**:
  - `backend/tools/financial_tools.py`
  - `backend/agents/health_score.py`
  - `backend/agents/whatif.py`
  - `backend/agents/twin.py`
- **Tests**: `backend/tests/test_deterministic_tools.py`, new Decimal precision test suite.
- **Rollback**: Revert commits; deterministic floating-point tests remain intact.

### Phase 2: Pluggable Document Ingestion Adapter Layer
- **Goal**: Create `DocumentParser` abstract base class with `LocalParser` (default) and `RagflowParser` (optional), backed by a strict validation gate.
- **Files Touched**:
  - `backend/ingestion/__init__.py`
  - `backend/ingestion/base.py`
  - `backend/ingestion/local_parser.py`
  - `backend/ingestion/ragflow_parser.py`
  - `backend/ingestion/validator.py`
  - `backend/agents/ingestion_agent.py`
- **Tests**: `backend/tests/test_ingestion_adapters.py` (mocked RAGFlow responses, corrupted PDFs, fallback verification).
- **Rollback**: Set `DOCUMENT_PARSER=local` in configuration.

### Phase 3: Pluggable Knowledge Retrieval Adapter Layer
- **Goal**: Create `KnowledgeRetriever` abstract base class with `NullKnowledgeBase` (default) and `RagflowKnowledgeBase` (optional) for citations.
- **Files Touched**:
  - `backend/knowledge/__init__.py`
  - `backend/knowledge/base.py`
  - `backend/knowledge/null_retriever.py`
  - `backend/knowledge/ragflow_retriever.py`
  - `backend/agents/rag.py`
- **Tests**: `backend/tests/test_knowledge_adapters.py`.
- **Rollback**: Set `KNOWLEDGE_RETRIEVER=null` in configuration.

### Phase 4: LangGraph Pipeline Integration & RAGFlow Enrichment
- **Goal**: Wire ingestion and knowledge adapters into LangGraph orchestrator nodes with zero breaking changes to existing DAG.
- **Files Touched**:
  - `backend/orchestrator/pipeline.py`
  - `backend/agents/copilot.py`
  - `backend/agents/explainer.py`
- **Tests**: `backend/tests/test_pipeline_e2e.py`.
- **Rollback**: Toggle feature flag to bypass enrichment step.

### Phase 5: FastMCP Server Exposure for External Agents
- **Goal**: Expose deterministic financial tools via a lightweight, authenticated FastMCP server so external agent frameworks (Hermes, Claude Desktop) can connect.
- **Files Touched**:
  - `backend/mcp_server/__init__.py`
  - `backend/mcp_server/server.py`
  - `backend/tools/registry.py`
- **Tests**: `backend/tests/test_mcp_server.py`.
- **Rollback**: Disable MCP server entrypoint without touching main FastAPI app.

### Phase 6: Authentication, RBAC, and Per-User Tenant Hardening
- **Goal**: Add JWT/Bearer token authentication, strict tenant scoping, and PII log redaction.
- **Files Touched**:
  - `backend/main.py`
  - `backend/db/database.py`
- **Tests**: `backend/tests/test_auth_isolation.py`.
- **Rollback**: Revert auth middleware to permissive development mode.

### Phase 7: Comprehensive Test Suite & Adversarial Validation
- **Goal**: Run complete test matrix: 100% offline tests, live/mock RAGFlow tests, prompt-injection resilience, and stress tests.
- **Files Touched**:
  - `backend/tests/*`
- **Tests**: Execute full test suite across all modules.

### Phase 8: Documentation, Runbooks & Deployment Specs
- **Goal**: Produce architecture runbooks, environment variable templates (`.env.example`), and Docker Compose setup for optional RAGFlow deployment.
- **Files Touched**:
  - `docs/architecture.md`
  - `docs/ragflow-integration.md`
  - `backend/.env.example`

---

## 7. Next Steps & Approval Gate

**STOPPING HERE AS DIRECTED BY PHASE 0.**

Awaiting user approval of `docs/phase0-audit.md` before proceeding to **Phase 1: Decimal Precision & Strict Financial Math Hardening**.
