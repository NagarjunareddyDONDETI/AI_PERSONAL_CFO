<div align="center">

# 💎 AI Personal CFO (FINZO)

### *Autonomous Multi-Agent Wealth Intelligence, Deterministic Decimal Engine, RAGFlow Knowledge & Model Context Protocol (MCP)*

[![Vercel Frontend](https://img.shields.io/badge/Frontend-Live%20on%20Vercel-000000?style=for-the-badge&logo=vercel&logoColor=white)](https://frontend-tau-dusky-gn8njz3yo4.vercel.app)
[![Render Frontend](https://img.shields.io/badge/Frontend-Live%20on%20Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://ai-cfo-frontend.onrender.com)
[![Render Backend](https://img.shields.io/badge/Backend%20API-Live%20on%20Render-46E3B7?style=for-the-badge&logo=render&logoColor=white)](https://ai-cfo-backend-nxaf.onrender.com)
[![CI/CD Pipeline](https://img.shields.io/badge/GitHub%20Actions-CI%2FCD%20Active-2088FF?style=for-the-badge&logo=githubactions&logoColor=white)](https://github.com/NagarjunareddyDONDETI/AI_PERSONAL_CFO/actions)
[![Tests Passing](https://img.shields.io/badge/Tests-562%20Passed-brightgreen?style=for-the-badge&logo=pytest&logoColor=white)](https://github.com/NagarjunareddyDONDETI/AI_PERSONAL_CFO)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  <a href="https://frontend-tau-dusky-gn8njz3yo4.vercel.app"><strong>Explore Live on Vercel »</strong></a>
  ·
  <a href="https://ai-cfo-frontend.onrender.com"><strong>Explore Live on Render »</strong></a>
  <br/>
  <a href="https://ai-cfo-backend-nxaf.onrender.com/docs">API Swagger Docs</a>
  ·
  <a href="#-system-architecture">Architecture</a>
  ·
  <a href="#-getting-started-locally">Local Setup</a>
  ·
  <a href="#-features">Features</a>
  ·
  <a href="docs/mcp-server-guide.md">MCP Server</a>
  ·
  <a href="docs/ragflow-integration-guide.md">RAGFlow Guide</a>
</p>

</div>

---

## 📖 Overview

**AI Personal CFO (FINZO)** is an enterprise-grade financial intelligence platform designed to replace conventional, passive budgeting apps with an **autonomous committee of specialized AI financial agents** backed by a **100% deterministic mathematical calculation engine**.

### Core Non-Negotiable Invariants:
1. **THE LLM NEVER DOES FINANCIAL MATH**: All monetary computations (cashflow, savings rates, debt payoff timelines, compound interest, health scoring, and forecasts) use pure Python `Decimal` arithmetic with `ROUND_HALF_UP`. The LLM only explains verified outputs.
2. **RAGFlow is OPTIONAL & Isolated**: Document layout parsing and regulatory knowledge retrieval integrate behind clean adapter interfaces with instant zero-dependency local fallbacks (`LocalParser` and `NullKnowledgeBase`).
3. **Single Source of Structured Truth**: The Financial Twin, user accounts, transactions, and goals live strictly in the database (SQLite WAL / PostgreSQL).
4. **Documents are DATA, Never Instructions**: Document text is strictly untrusted and sanitized against prompt-injection attacks.
5. **Model Context Protocol (MCP) Support**: Exposes the deterministic financial calculation engine to external autonomous agents (NousResearch Hermes Agent, Claude Desktop, Cursor) via standard JSON-RPC 2.0.

---

## 🌐 Live Deployments

| Component | Cloud Platform | Live URL | Status |
| :--- | :--- | :--- | :--- |
| **Frontend Web App (Primary)** | Vercel Edge Network | [https://frontend-tau-dusky-gn8njz3yo4.vercel.app](https://frontend-tau-dusky-gn8njz3yo4.vercel.app) | ![Live](https://img.shields.io/badge/Status-Operational-brightgreen) |
| **Frontend Web App (Mirror)** | Render Static Site | [https://ai-cfo-frontend.onrender.com](https://ai-cfo-frontend.onrender.com) | ![Live](https://img.shields.io/badge/Status-Operational-brightgreen) |
| **Backend REST API** | Render Web Service | [https://ai-cfo-backend-nxaf.onrender.com](https://ai-cfo-backend-nxaf.onrender.com) | ![Live](https://img.shields.io/badge/Status-Operational-brightgreen) |
| **Interactive API Docs** | Swagger / OpenAPI | [https://ai-cfo-backend-nxaf.onrender.com/docs](https://ai-cfo-backend-nxaf.onrender.com/docs) | ![Interactive](https://img.shields.io/badge/Docs-Swagger%20UI-blue) |

---

## 🛠️ Tech Stack

<div align="center">

| Layer | Technologies |
| :--- | :--- |
| **Frontend UI/UX** | ![React](https://img.shields.io/badge/React_18-20232A?style=flat-square&logo=react&logoColor=61DAFB) ![TypeScript](https://img.shields.io/badge/TypeScript_5.6-007ACC?style=flat-square&logo=typescript&logoColor=white) ![Vite](https://img.shields.io/badge/Vite_5-646CFF?style=flat-square&logo=vite&logoColor=white) ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS_3.4-38B2AC?style=flat-square&logo=tailwind-css&logoColor=white) ![Framer Motion](https://img.shields.io/badge/Framer_Motion-black?style=flat-square&logo=framer&logoColor=blue) |
| **3D & Data Viz** | ![Three.js](https://img.shields.io/badge/Three.js-black?style=flat-square&logo=three.js&logoColor=white) ![React Three Fiber](https://img.shields.io/badge/React_Three_Fiber-gray?style=flat-square&logo=react&logoColor=white) ![Recharts](https://img.shields.io/badge/Recharts-22b5bf?style=flat-square) |
| **Backend Framework** | ![FastAPI](https://img.shields.io/badge/FastAPI_0.115-005571?style=flat-square&logo=fastapi) ![Python](https://img.shields.io/badge/Python_3.12-3776AB?style=flat-square&logo=python&logoColor=white) ![Uvicorn](https://img.shields.io/badge/Uvicorn-499848?style=flat-square&logo=gunicorn&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic_V2-e92063?style=flat-square) |
| **Deterministic Engine** | ![Python Decimal](https://img.shields.io/badge/Deterministic_Math-Decimal_Precision-success?style=flat-square) ![NumPy](https://img.shields.io/badge/NumPy-013243?style=flat-square&logo=numpy&logoColor=white) ![Pandas](https://img.shields.io/badge/Pandas-150458?style=flat-square&logo=pandas&logoColor=white) ![Scikit Learn](https://img.shields.io/badge/Scikit--Learn-F7931E?style=flat-square&logo=scikit-learn&logoColor=white) |
| **Multi-Agent & RAG** | ![LangGraph](https://img.shields.io/badge/LangGraph_0.2-1C3C3C?style=flat-square) ![MCP](https://img.shields.io/badge/Model_Context_Protocol-MCP_2024--11--05-blueviolet?style=flat-square) ![ChromaDB](https://img.shields.io/badge/ChromaDB_Vector_Store-orange?style=flat-square) ![RAGFlow](https://img.shields.io/badge/RAGFlow-Optional_DeepDoc-purple?style=flat-square) |
| **Voice & Speech AI** | ![Groq Whisper](https://img.shields.io/badge/Groq_Whisper_STT-f55036?style=flat-square) ![Edge TTS](https://img.shields.io/badge/Edge_TTS_gTTS-0078D7?style=flat-square) |
| **Database & Auth** | ![SQLite WAL](https://img.shields.io/badge/SQLite_3_WAL-07405E?style=flat-square&logo=sqlite&logoColor=white) ![JWT Auth](https://img.shields.io/badge/JWT_Tokens-000000?style=flat-square&logo=json-web-tokens&logoColor=white) ![PBKDF2](https://img.shields.io/badge/PBKDF2_SHA256-600k_Iterations-critical?style=flat-square) |
| **DevOps & CI/CD** | ![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat-square&logo=github-actions&logoColor=white) ![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat-square&logo=vercel&logoColor=white) ![Render](https://img.shields.io/badge/Render_Cloud-46E3B7?style=flat-square&logo=render&logoColor=white) ![Pytest](https://img.shields.io/badge/Pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white) |

<br/>

<img src="https://skillicons.dev/icons?i=react,ts,tailwind,threejs,fastapi,py,sqlite,githubactions" alt="Tech Stack Icons" />

</div>

---

## ✨ Key Features

### 1. 🤖 Multi-Agent Financial Committee (LangGraph)
User financial decisions undergo a structured, data-grounded debate between specialized AI persona agents:
- **🛡️ Risk Auditor Agent**: Stress-tests decisions against emergency fund runway, DTI ratios, and economic drawdowns.
- **📈 Growth Strategist Agent**: Calculates opportunity cost, asset allocation, and aggressive compounding potential.
- **⚖️ Tax & Cashflow Specialist**: Analyzes tax efficiency, deduction opportunities, and liquidity constraints.
- **🎯 Chief Decider (CFO)**: Evaluates agent arguments, balances conflicting tradeoffs, and produces a final synthesis with confidence ratings.

### 2. 🧮 Deterministic Financial Calculation Engine
- 8 mathematically proven tools for cashflow, emergency runway, debt avalanche/snowball payoff schedules, compound interest projections, IQR spending anomaly detection, and 0-100 financial health scores.
- Zero floating-point rounding errors through explicit `Decimal` precision.

### 3. 🔌 Pluggable RAGFlow Ingestion & Knowledge Adapters
- Multi-format statement parser (`pdfplumber`, `openpyxl`, `chardet`, `csv`) with optional DeepDoc OCR via RAGFlow.
- Regulatory and tax guidance citations retrieved dynamically or served offline via `NullKnowledgeBase`.

### 4. ⚡ FastMCP Server for External Agents
- Standard Model Context Protocol (MCP) JSON-RPC 2.0 interface in `backend/mcp_server/server.py`.
- Integrates seamlessly with NousResearch Hermes Agent, Claude Desktop, Cursor, and IDE extensions.

### 5. 🎙️ "Finzo" Voice Financial Assistant
- Real-time voice Q&A powered by Groq Whisper STT and natural speech synthesis.
- Context-aware long-term memory across 13 distinct financial categories.

### 6. 🔮 3D Spatial RAG Visualizer (ChromaDB + Three.js)
- Inspect how queries and knowledge chunks interact in 3D vector space.
- Interactive PCA projections of 384-dimensional embeddings into an orbitable visualization.

### 7. 📊 Digital Financial Twin & What-If Simulations
- Multi-year probabilistic net worth trajectories under Bull, Baseline, and Bear economic regimes.
- Sandbox modeling for career changes, home purchases, student loan payoffs, and sabbaticals.

---

## 🏛️ System Architecture

```
                                  ┌──────────────────────────────┐
                                  │      Client (Browser)        │
                                  │   React 18 + Three.js 3D     │
                                  └──────────────┬───────────────┘
                                                 │ HTTP / REST & WebSockets
                                                 ▼
                                  ┌──────────────────────────────┐
                                  │    FastAPI Gateway Server    │
                                  │  (JWT Auth & Rate Limiting)  │
                                  └──────┬───────────────┬───────┘
                                         │               │
                   ┌─────────────────────┴───────┐       │
                   ▼                             ▼       ▼
     ┌───────────────────────────┐ ┌───────────────────────────┐ ┌───────────────────────────┐
     │   LangGraph Pipeline DAG  │ │ Deterministic Tool Engine │ │ Pluggable RAGFlow / KB    │
     │ ┌───────────────────────┐ │ │ ┌───────────────────────┐ │ │ ┌───────────────────────┐ │
     │ │ Ingestion -> Clean    │ │ │ │ Decimal Cashflow Math │ │ │ │ Local / DeepDoc Ingest  │ │
     │ │ Categorize -> Agg     │ │ │ │ Debt Payoff Schedule  │ │ │ │ Grounded Citations      │ │
     │ │ Anomaly -> Forecast   │ │ │ │ Health Score (0-100)  │ │ │ │ Offline Null Fallback   │ │
     │ │ 8-Specialist Debate   │ │ │ │ Compound Growth Proj  │ │ │ └───────────────────────┘ │
     │ └───────────────────────┘ │ │ └───────────────────────┘ │ └───────────────────────────┘
     └─────────────┬─────────────┘ └─────────────┬─────────────┘
                   │                             │
                   ▼                             ▼
     ┌─────────────────────────────────────────────────────────┐
     │                 SQLite (WAL) + Caching                  │
     └─────────────────────────────────────────────────────────┘
                   ▲
                   │ MCP Protocol (JSON-RPC 2.0)
     ┌─────────────┴─────────────┐
     │ External Agents (Hermes,  │
     │ Claude Desktop, Cursor)   │
     └───────────────────────────┘
```

---

## 🚀 Getting Started Locally

### Prerequisites
- **Node.js**: v18.0+ or v20.0+
- **Python**: v3.11+ or v3.12+
- **Git**

### 1. Clone the Repository
```bash
git clone https://github.com/NagarjunareddyDONDETI/AI_PERSONAL_CFO.git
cd AI_PERSONAL_CFO
```

---

### 2. Backend Setup
```bash
cd backend

# Create & activate virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start FastAPI development server
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
*Backend API will be accessible at: `http://localhost:8000` (Swagger UI at `/docs`)*

---

### 3. Frontend Setup
```bash
cd frontend

# Install npm dependencies
npm install

# Start Vite development server
npm run dev
```
*Frontend will be running at: `http://localhost:5173`*

---

## 🧪 Running Automated Tests

The repository includes a comprehensive 562-test suite covering authentication, deterministic financial calculations, prompt-injection defense, LangGraph state nodes, RAG retrieval, MCP server JSON-RPC, and voice endpoints:

```bash
cd backend
pytest tests -v
```

```
============================== 562 passed in 99.60s ==============================
```

---

## 📡 API Endpoint Overview

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :---: |
| `GET` | `/health` | Health probe & service status | No |
| `GET` | `/capabilities` | Available features & active AI models | No |
| `POST` | `/auth/register` | Create a new user account | No |
| `POST` | `/auth/login` | Authenticate user & receive JWT token | No |
| `GET` | `/auth/me` | Retrieve authenticated profile | **Yes** |
| `POST` | `/upload` | Ingest bank statement (PDF/CSV/XLSX) | **Yes** |
| `POST` | `/debate/run` | Execute multi-agent committee debate | **Yes** |
| `POST` | `/rag/query` | RAG context retrieval & 3D vector trace | **Yes** |
| `POST` | `/twin/simulate` | Run Monte Carlo wealth simulation | **Yes** |
| `POST` | `/voice/ask` | Finzo voice conversational pipeline | **Yes** |
| `GET` | `/goals` | List user financial targets & milestones | **Yes** |

---

## 🔄 CI/CD & Deployment Pipeline

This repository is configured with an automated GitHub Actions CI/CD workflow located at [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml):

- **Automated Validation on Push / PR**: Runs Python 3.12 pytest suite and frontend TypeScript/Vite compilation.
- **Continuous Deployment to Render & Vercel**: Triggers instant zero-downtime rolling deploys upon merging to `main`.
- **Post-Deploy Smoke Testing**: Verifies live endpoint health and availability automatically.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome!
1. Fork the Project (`https://github.com/NagarjunareddyDONDETI/AI_PERSONAL_CFO/fork`)
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📜 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

<div align="center">
  <sub>Built with ❤️ by <a href="https://github.com/NagarjunareddyDONDETI">Nagarjuna Reddy Dondeti</a></sub>
</div>
