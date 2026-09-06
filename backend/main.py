"""AI Personal CFO — FastAPI backend.

Wires the deterministic pipeline (Phases 1-2), RAG (Phase 3), explainer/LLM
(Phase 4), what-if simulator (Phase 5), and voice (Phase 6) behind one API.

Authentication: every endpoint that touches user data resolves the caller from a
bearer token via the ``current_user`` dependency. No endpoint accepts a user id
from the client — that is what made it possible to read or delete anyone's data.
"""
from __future__ import annotations

import io
import os
import secrets

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

import llm  # noqa: E402
import auth  # noqa: E402
from auth.deps import CurrentUser, CurrentUserId, is_valid_email, normalize_email  # noqa: E402
from agents import llm_client  # noqa: E402
from agents import twin  # noqa: E402
from agents.copilot import converse  # noqa: E402
from agents.debate import list_agents, run_debate  # noqa: E402
from agents import memory as memory_agent  # noqa: E402
from agents.explainability import SUBJECTS as EXPLAIN_SUBJECTS  # noqa: E402
from agents.explainability import build_explanation  # noqa: E402
from agents import goal_planner  # noqa: E402
from agents.twin import ScenarioInput  # noqa: E402
from agents.explainer import explain  # noqa: E402
from agents.ingestion_agent import IngestionError  # noqa: E402
from agents.whatif import simulate_purchase  # noqa: E402
from db import database  # noqa: E402
from llm import Message  # noqa: E402
from llm.router import router as llm_router  # noqa: E402
from orchestrator.pipeline import run_pipeline, using_langgraph  # noqa: E402
from orchestrator.trace import WORKFLOW_NODES, build_graph  # noqa: E402
from rag import retriever  # noqa: E402
from voice import voice_service  # noqa: E402

app = FastAPI(title="AI Personal CFO", version="1.0.0")

# CORS: restrict origins in production via ALLOWED_ORIGINS (comma-separated).
# Default "*" for local dev. Credentials are only enabled when origins are
# explicitly listed, since "*" + credentials is rejected by browsers and unsafe.
_origins_env = os.getenv("ALLOWED_ORIGINS", "*").strip()
_allow_origins = (
    ["*"] if _origins_env == "*"
    else [o.strip() for o in _origins_env.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
_SAMPLES_DIR = os.path.join(_DATA_DIR, "sample_statements")

# Last workflow trace per user (Phase 7). In-memory so revisiting the dashboard
# shows the real per-node timings without re-persisting/polluting score history.
_LAST_WORKFLOW: dict[str, dict] = {}


@app.on_event("startup")
def _startup() -> None:
    database.init_db()
    # Warm up Whisper + RAG in the background so the first request is fast.
    import threading

    threading.Thread(target=voice_service.preload, daemon=True).start()
    threading.Thread(target=retriever.preload, daemon=True).start()


# ---------- Phase 0 ----------
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/capabilities")
def capabilities() -> dict:
    """Report which optional subsystems are live vs degraded."""
    return {
        "llm_configured": llm_client.is_configured(),
        "llm_providers": llm_router.available_providers(),
        "rag_available": retriever.is_available(),
        "langgraph": using_langgraph(),
        "whisper": voice_service.whisper_available(),
        "gtts": voice_service.gtts_available(),
        "voice": voice_service.capabilities(),
        "auth_required": True,
        # Warns the operator that sessions will not survive a restart.
        "ephemeral_auth_secret": auth.using_ephemeral_secret(),
    }


# ---------- Authentication ----------
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password.",
    headers={"WWW-Authenticate": "Bearer"},
)

# Verifying against this when no account exists keeps the timing of "unknown
# email" and "wrong password" comparable, so login cannot be used to enumerate
# which addresses are registered.
_DUMMY_HASH = auth.hash_password(secrets.token_urlsafe(16))


def _client_ip(request: Request) -> str:
    """Best-effort client address for rate-limit keys.

    Trusts X-Forwarded-For, which is only safe behind a proxy that sets it. A
    direct-to-internet deployment can have this spoofed, which is why the email
    is part of the key too.
    """
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return request.client.host if request.client else "unknown"


def _public_user(user: dict) -> dict:
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user.get("name") or "",
        "created_at": user.get("created_at"),
        "last_login_at": user.get("last_login_at"),
    }


def _session_response(user: dict) -> dict:
    token, expires_at = auth.create_access_token(
        user["user_id"], email=user["email"]
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": _public_user(user),
    }


def _new_user_id() -> str:
    """Opaque, unguessable account id used as the key for all user data."""
    for _ in range(5):
        candidate = f"u_{secrets.token_urlsafe(12)}"
        if not database.user_id_exists(candidate):
            return candidate
    raise HTTPException(status_code=500, detail="Could not allocate a user id.")


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginRequest(BaseModel):
    email: str
    password: str


@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, request: Request) -> dict:
    """Create an account and return a session token."""
    email = normalize_email(req.email)
    if not is_valid_email(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    problem = auth.validate_password_strength(req.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    limit_key = f"register:{_client_ip(request)}"
    retry_after = auth.register_limiter.check(limit_key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-up attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    # Count every attempt, not just failures: capping successes is what stops one
    # client from mass-creating accounts, and counting duplicates is what stops
    # this endpoint being used to check which addresses are already registered.
    auth.register_limiter.record_failure(limit_key)

    try:
        user = database.create_user(
            _new_user_id(),
            email,
            auth.hash_password(req.password),
            (req.name or "").strip()[:120],
        )
    except database.EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered.",
        ) from None

    database.touch_last_login(user["user_id"])
    return _session_response(user)


@app.post("/auth/login")
def login(req: LoginRequest, request: Request) -> dict:
    """Exchange credentials for a bearer token."""
    email = normalize_email(req.email)
    limit_key = f"login:{_client_ip(request)}:{email}"
    retry_after = auth.login_limiter.check(limit_key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed attempts. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    record = database.get_user_by_email(email, with_password=True)
    stored = record["password_hash"] if record else _DUMMY_HASH
    if not auth.verify_password(req.password, stored) or record is None:
        auth.login_limiter.record_failure(limit_key)
        raise _INVALID_CREDENTIALS

    auth.login_limiter.reset(limit_key)
    # Upgrade the stored hash if the KDF cost has since been raised.
    if auth.needs_rehash(stored):
        database.update_password_hash(
            record["user_id"], auth.hash_password(req.password)
        )
    database.touch_last_login(record["user_id"])
    record.pop("password_hash", None)
    return _session_response(record)


@app.get("/auth/me")
def read_me(user: CurrentUser) -> dict:
    """Validate the caller's token and echo their profile."""
    return {"user": _public_user(user)}


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/password")
def change_password(req: PasswordChangeRequest, user: CurrentUser) -> dict:
    """Change the caller's password after re-verifying the current one."""
    record = database.get_user_by_email(user["email"], with_password=True)
    if record is None or not auth.verify_password(
        req.current_password, record["password_hash"]
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect.",
        )
    problem = auth.validate_password_strength(req.new_password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    database.update_password_hash(
        user["user_id"], auth.hash_password(req.new_password)
    )
    # Existing tokens stay valid until they expire; this API has no server-side
    # session store to revoke them from.
    return {"status": "password_updated"}


@app.delete("/auth/me")
def delete_account(user: CurrentUser) -> dict:
    """Delete the caller's account and all of their financial data."""
    database.delete_user(user["user_id"])
    return {"status": "deleted"}


# ---------- LLM router: health, metrics, direct access, streaming ----------
@app.get("/health/llm")
async def health_llm(_: CurrentUserId) -> dict:
    """Per-provider health plus the currently active provider."""
    return await llm_router.health_check()


@app.get("/metrics/llm")
def metrics_llm(_: CurrentUserId) -> dict:
    """Aggregate LLM usage metrics (latency, tokens, errors, cost, cache)."""
    return llm.metrics.snapshot()


# ---------- Phase 8: Model Routing (monitoring + selection) ----------
_PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "groq": "Groq",
    "github": "GitHub Models (OpenAI)",
    "openrouter": "OpenRouter (Claude/OpenAI/…)",
    "ollama": "Ollama (local, offline)",
}


@app.get("/router/status")
async def router_status(_: CurrentUserId) -> dict:
    """Consolidated view for the model-routing dashboard: per-provider health,
    priority rank, availability, plus aggregate metrics and the active provider.
    """
    health = await llm_router.health_check()
    metrics = llm.metrics.snapshot()
    order = llm_router.all_providers()
    available = set(llm_router.available_providers())
    per = metrics.get("providers", {})

    providers = []
    for rank, name in enumerate(order, start=1):
        pm = per.get(name, {})
        reqs = pm.get("requests", 0) or 0
        # metrics.as_dict() publishes the average directly; it does not expose
        # total_latency_ms, so recomputing it here always yielded 0.
        avg_latency = pm.get("avg_latency_ms", 0.0) or 0.0
        providers.append({
            "name": name,
            "label": _PROVIDER_LABELS.get(name, name),
            "rank": rank,
            "model": getattr(llm_router._providers[name], "model", ""),
            "status": health.get(name, "not_configured"),
            "available": name in available,
            "offline": name == "ollama",
            "requests": reqs,
            "avg_latency_ms": round(avg_latency, 1),
            "errors": pm.get("errors", 0),
            "total_tokens": pm.get("total_tokens", 0),
            "cost_estimate_usd": pm.get("cost_estimate_usd", 0.0),
        })

    return {
        "providers": providers,
        "preferred": llm_router.preferred(),
        "active_provider": health.get("active_provider", "none"),
        "last_provider": llm_router.last_provider,
        "totals": metrics.get("totals", {}),
        "cache": metrics.get("cache", {}),
    }


class ProviderSelectRequest(BaseModel):
    provider: str = "auto"


@app.post("/router/provider")
def router_set_provider(req: ProviderSelectRequest, _: CurrentUserId) -> dict:
    """Set the preferred provider at runtime ('auto' restores the full chain)."""
    try:
        chosen = llm_router.set_preferred(req.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"preferred": chosen, "selection": llm_router._selection()}


class LLMChatRequest(BaseModel):
    messages: list[dict] = Field(..., description="[{role, content}, ...]")
    temperature: float = 0.7
    max_tokens: int | None = None
    use_cache: bool = True


@app.post("/llm/chat")
async def llm_chat(req: LLMChatRequest, _: CurrentUserId) -> dict:
    """Direct router access: returns the first successful provider response."""
    try:
        msgs = [Message(**m) for m in req.messages]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid messages: {exc}") from exc
    try:
        resp = await llm_router.chat(
            msgs,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            use_cache=req.use_cache,
        )
    except llm.ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return resp.model_dump()


@app.post("/llm/stream")
async def llm_stream(req: LLMChatRequest, _: CurrentUserId):
    """Stream tokens in real time (text/event-stream) with provider failover."""
    try:
        msgs = [Message(**m) for m in req.messages]
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid messages: {exc}") from exc

    async def event_source():
        try:
            async for chunk in llm_router.stream(
                msgs, temperature=req.temperature, max_tokens=req.max_tokens
            ):
                yield f"data: {chunk}\n\n"
        except llm.ProviderError as exc:
            yield f"data: [error] {exc}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _serialize(state: dict) -> dict:
    return {
        "user_id": state.get("user_id"),
        "transactions": state.get("categorized", []),
        "monthly_summary": state.get("monthly_summary", {}),
        "anomalies": state.get("anomalies", []),
        "forecast": state.get("forecast", {}),
        "health_score": state.get("health_score", {}),
        "savings_suggestions": state.get("savings_suggestions", []),
    }


_FORMAT_LABELS = {
    "csv": "CSV", "tsv": "TSV", "txt": "Text", "xlsx": "Excel", "xlsm": "Excel",
    "xls": "Excel (legacy)", "ods": "OpenDocument", "json": "JSON", "pdf": "PDF",
}


def _process_csv(content: str | bytes, user_id: str, filename: str | None = None) -> dict:
    from orchestrator.pipeline import run_pipeline_traced
    from orchestrator.trace import WorkflowTracer

    tracer = WorkflowTracer()
    name = (filename or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    size = len(content) if content is not None else 0
    fmt = _FORMAT_LABELS.get(ext, ext.upper() or "auto")
    tracer.record("upload", "ok", 0.0, 0, None, f"{fmt} • {size:,} bytes")

    try:
        state = run_pipeline_traced(content, user_id, filename, tracer)
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Processing failed: {exc}") from exc

    result = _serialize(state)

    def _persist() -> dict:
        database.save_transactions(user_id, state.get("categorized", []))
        database.save_result(user_id, result)
        return result

    def _remember() -> int:
        try:
            retriever.index_user_memory(user_id, state)
        except Exception:  # noqa: BLE001
            pass
        try:
            return memory_agent.remember_from_result(user_id, result)
        except Exception:  # noqa: BLE001
            return 0

    tracer.step("persist", _persist, detail_fn=lambda _o: "saved")
    tracer.step(
        "memory", _remember,
        detail_fn=lambda n: f"{n} facts remembered" if isinstance(n, int) else "indexed",
    )

    result["workflow"] = {
        "trace": tracer.as_list(),
        "edges": [{"from": a["id"], "to": b["id"]}
                  for a, b in zip(WORKFLOW_NODES, WORKFLOW_NODES[1:])],
        "langgraph": using_langgraph(),
        "total_ms": tracer.total_ms(),
        "format": fmt,
    }
    _LAST_WORKFLOW[user_id] = result["workflow"]
    return result


# ---------- Phase 1 ----------
_SUPPORTED_EXTS = {"csv", "tsv", "txt", "xlsx", "xlsm", "xls", "ods", "json", "pdf"}


@app.post("/upload")
async def upload(user_id: CurrentUserId, file: UploadFile = File(...)) -> dict:
    name = (file.filename or "").strip()
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext and ext not in _SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '.{ext}'. Supported: "
                + ", ".join(sorted(_SUPPORTED_EXTS))
                + "."
            ),
        )
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    # Pass raw bytes through; the ingestion layer decodes/decodes per format.
    return _process_csv(raw, user_id, filename=name or "upload.csv")


@app.get("/samples")
def list_samples() -> dict:
    if not os.path.isdir(_SAMPLES_DIR):
        return {"samples": []}
    return {
        "samples": sorted(
            f for f in os.listdir(_SAMPLES_DIR) if f.lower().endswith(".csv")
        )
    }


@app.post("/load-sample")
def load_sample(user_id: CurrentUserId, name: str = Form(...)) -> dict:
    safe = os.path.basename(name)
    path = os.path.join(_SAMPLES_DIR, safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"Sample not found: {safe}")
    with open(path, "r", encoding="utf-8-sig") as fh:
        content = fh.read()
    # Pass the sample's filename so the workflow reports the real format.
    return _process_csv(content, user_id, filename=safe)


def _require_result(user_id: str) -> dict:
    result = database.get_result(user_id)
    if result is None:
        raise HTTPException(
            status_code=404, detail="No data yet. Upload a statement first."
        )
    return result


@app.get("/dashboard")
def dashboard(user_id: CurrentUserId) -> dict:
    return _require_result(user_id)


@app.get("/forecast")
def forecast(user_id: CurrentUserId) -> dict:
    return _require_result(user_id).get("forecast", {})


@app.get("/health-score")
def health_score(user_id: CurrentUserId) -> dict:
    return _require_result(user_id).get("health_score", {})


# ---------- Phase 4: chat ----------
class ChatRequest(BaseModel):
    query: str


@app.post("/chat")
def chat(req: ChatRequest, user_id: CurrentUserId) -> dict:
    """Memory-aware copilot: grounds answers in computed data + RAG + history
    + durable long-term memory (Phase 5)."""
    result = _require_result(user_id)
    history = database.get_conversation(user_id, limit=20)
    rag = retriever.retrieve(req.query, user_id)
    memory_context = memory_agent.recall_context(user_id)
    answer = converse(req.query, result, rag, history, memory_context=memory_context)
    # Persist both turns so follow-up questions have context.
    database.save_message(user_id, "user", req.query)
    database.save_message(
        user_id,
        "assistant",
        answer["response"],
        intent=answer.get("intent"),
        llm_used=answer.get("llm_used"),
    )
    # Keep a rolling durable summary of recent topics.
    try:
        memory_agent.summarize_conversation(
            user_id, history + [{"role": "user", "content": req.query}]
        )
    except Exception:  # noqa: BLE001
        pass
    return answer


@app.get("/chat/history")
def chat_history(user_id: CurrentUserId) -> dict:
    """Return the persisted conversation for a user (chronological)."""
    return {"history": database.get_conversation(user_id, limit=200)}


# ---------- Phase 2: multi-agent debate ----------
class DebateRequest(BaseModel):
    question: str = ""


@app.post("/debate")
def debate(req: DebateRequest, user_id: CurrentUserId) -> dict:
    """Run the specialist panel over the user's computed financial state."""
    result = _require_result(user_id)
    return run_debate(result, req.question)


@app.get("/debate/agents")
def debate_agents() -> dict:
    """List the specialist panel (metadata for the UI)."""
    return {"agents": list_agents()}


# ---------- Phase 4: Explainable AI ----------
# ---------- Phase 9: Goal Planner ----------
@app.get("/goals/types")
def goal_types_endpoint() -> dict:
    """List supported goal presets."""
    return {"types": goal_planner.goal_types()}


class GoalCreateRequest(BaseModel):
    name: str
    goal_type: str = "custom"
    target_amount: float
    current_saved: float = 0.0
    target_months: int | None = None
    monthly_contribution: float | None = None
    annual_return: float = Field(
        0.0, ge=0.0, le=1.0, description="Assumed annual return, e.g. 0.07 for 7%."
    )


def _plan_for_row(row: dict, surplus: float, ef_months: float) -> dict:
    plan = goal_planner.plan_goal(
        goal_type=row["goal_type"],
        target_amount=row["target_amount"],
        current_saved=row.get("current_saved", 0.0) or 0.0,
        target_months=row.get("target_months"),
        monthly_contribution=row.get("monthly_contribution"),
        monthly_surplus=surplus,
        emergency_fund_months=ef_months,
        annual_return=row.get("annual_return", 0.0) or 0.0,
    )
    return {"id": row.get("id"), "name": row.get("name"), **plan}


@app.post("/goals")
def create_goal(req: GoalCreateRequest, user_id: CurrentUserId) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="name is required.")
    if req.target_amount <= 0:
        raise HTTPException(status_code=422, detail="target_amount must be positive.")

    surplus, ef_months = goal_planner.surplus_from_result(database.get_result(user_id))
    goal_id = database.save_goal(
        user_id, req.name.strip(), req.goal_type, req.target_amount,
        req.current_saved, req.target_months, req.monthly_contribution,
        req.annual_return,
    )
    # Mirror into long-term memory so the copilot is aware of the goal.
    try:
        memory_agent.add_goal(user_id, req.name.strip(), req.target_amount)
    except Exception:  # noqa: BLE001
        pass

    row = {
        "id": goal_id, "name": req.name.strip(), "goal_type": req.goal_type,
        "target_amount": req.target_amount, "current_saved": req.current_saved,
        "target_months": req.target_months, "monthly_contribution": req.monthly_contribution,
        "annual_return": req.annual_return,
    }
    return {"goal": _plan_for_row(row, surplus, ef_months)}


@app.get("/goals")
def list_goals_endpoint(user_id: CurrentUserId) -> dict:
    """Return the user's goals, each with a freshly-computed plan."""
    surplus, ef_months = goal_planner.surplus_from_result(database.get_result(user_id))
    goals = [_plan_for_row(r, surplus, ef_months) for r in database.list_goals(user_id)]
    return {"goals": goals, "monthly_surplus": round(surplus, 2)}


@app.delete("/goals/{goal_id}")
def delete_goal_endpoint(goal_id: int, user_id: CurrentUserId) -> dict:
    # The user_id in the WHERE clause is what stops one account deleting
    # another's goal by guessing its integer id.
    ok = database.delete_goal(goal_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Goal not found.")
    return {"status": "deleted", "id": goal_id}


@app.get("/explain/subjects")
def explain_subjects() -> dict:
    """List the explainable dashboard subjects."""
    return {"subjects": EXPLAIN_SUBJECTS}


class ExplainRequest(BaseModel):
    subject: str = "score"


@app.post("/explain")
def explain_endpoint(req: ExplainRequest, user_id: CurrentUserId) -> dict:
    """Return a transparent explanation card for one dashboard figure."""
    result = _require_result(user_id)
    return build_explanation(req.subject, result, user_id)


# ---------- Phase 6: Retrieval Visualization ----------
class RagTraceRequest(BaseModel):
    query: str
    k: int = 4


@app.post("/rag/trace")
def rag_trace(req: RagTraceRequest, user_id: CurrentUserId) -> dict:
    """Return the full RAG retrieval trace for the interactive visualiser."""
    if not req.query.strip():
        raise HTTPException(status_code=422, detail="query is required.")
    return retriever.retrieve_trace(req.query.strip(), user_id, k=max(1, min(req.k, 10)))


# ---------- Phase 7: Workflow Visualization ----------
@app.get("/workflow/graph")
def workflow_graph() -> dict:
    """Static analysis-graph definition (skeleton for the visualiser)."""
    return {**build_graph(), "supported_formats": sorted(_SUPPORTED_EXTS), "langgraph": using_langgraph()}


@app.get("/workflow/trace")
def workflow_trace(user_id: CurrentUserId) -> dict:
    """Return the workflow trace from the user's last processed upload."""
    cached = _LAST_WORKFLOW.get(user_id)
    if cached:
        return cached
    result = database.get_result(user_id)
    if result and "workflow" in result:
        return result["workflow"]
    # No run yet — return the static graph skeleton so the UI can still render.
    return {
        **build_graph(),
        "trace": None,
        "langgraph": using_langgraph(),
        "supported_formats": sorted(_SUPPORTED_EXTS),
    }


# ---------- Phase 5: Long-Term Memory ----------
@app.get("/memory")
def get_memory(user_id: CurrentUserId) -> dict:
    """Return everything the assistant remembers, grouped by kind."""
    return {"memory": memory_agent.all_memories(user_id)}


class PreferenceRequest(BaseModel):
    key: str
    value: str


@app.post("/memory/preference")
def add_preference(req: PreferenceRequest, user_id: CurrentUserId) -> dict:
    if not req.key.strip() or not req.value.strip():
        raise HTTPException(status_code=422, detail="key and value are required.")
    return memory_agent.set_preference(user_id, req.key.strip(), req.value.strip())


class GoalRequest(BaseModel):
    name: str
    target_amount: float | None = None
    note: str = ""


@app.post("/memory/goal")
def add_goal(req: GoalRequest, user_id: CurrentUserId) -> dict:
    if not req.name.strip():
        raise HTTPException(status_code=422, detail="name is required.")
    return memory_agent.add_goal(
        user_id, req.name.strip(), req.target_amount, req.note.strip()
    )


@app.delete("/memory")
def clear_memory(user_id: CurrentUserId, kind: str | None = None) -> dict:
    """Clear a user's long-term memory (optionally only one kind)."""
    removed = database.delete_memories(user_id, kind)
    return {"status": "cleared", "removed": removed, "kind": kind}


# ---------- Phase 3: Digital Financial Twin ----------
def _build_scenario(user_id: str, overrides: dict) -> ScenarioInput:
    """Merge user-provided overrides onto data-derived defaults."""
    result = _require_result(user_id)
    merged = {**twin.defaults_from_result(result), **(overrides or {})}
    try:
        return ScenarioInput(**merged)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=f"Invalid scenario: {exc}") from exc


class TwinSimulateRequest(BaseModel):
    scenario: dict = Field(default_factory=dict)
    save: bool = False
    name: str | None = None


@app.post("/twin/simulate")
def twin_simulate(req: TwinSimulateRequest, user_id: CurrentUserId) -> dict:
    """Project the user's finances forward under one scenario."""
    scenario = _build_scenario(user_id, req.scenario)
    if req.name:
        scenario.name = req.name
    result = twin.simulate(scenario)
    payload = result.model_dump()
    saved_id = None
    if req.save:
        saved_id = database.save_simulation(
            user_id, scenario.name, scenario.model_dump(), payload
        )
    return {"result": payload, "saved_id": saved_id}


class TwinCompareRequest(BaseModel):
    scenarios: list[dict]


@app.post("/twin/compare")
def twin_compare(req: TwinCompareRequest, user_id: CurrentUserId) -> dict:
    """Run several scenarios side by side for comparison."""
    if not req.scenarios:
        raise HTTPException(status_code=422, detail="Provide at least one scenario.")
    results = []
    for overrides in req.scenarios:
        scenario = _build_scenario(user_id, overrides)
        results.append(twin.simulate(scenario).model_dump())
    return {"results": results}


@app.get("/twin/scenarios")
def twin_scenarios(user_id: CurrentUserId) -> dict:
    """List a user's saved simulations."""
    return {"scenarios": database.list_simulations(user_id)}


@app.delete("/twin/scenario/{sim_id}")
def twin_delete(sim_id: int, user_id: CurrentUserId) -> dict:
    ok = database.delete_simulation(sim_id, user_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Simulation not found.")
    return {"status": "deleted", "id": sim_id}


@app.delete("/chat/history")
def clear_chat_history(user_id: CurrentUserId) -> dict:
    """Clear a user's conversation memory."""
    removed = database.clear_conversation(user_id)
    return {"status": "cleared", "removed": removed}


# ---------- Phase 5: what-if ----------
class WhatIfRequest(BaseModel):
    purchase_amount: float
    tenure_months: int = 12
    current_savings: float | None = None
    explain: bool = True


@app.post("/whatif")
def whatif(req: WhatIfRequest, user_id: CurrentUserId) -> dict:
    result = _require_result(user_id)
    sim = simulate_purchase(
        req.purchase_amount,
        result.get("monthly_summary", {}),
        result.get("health_score", {}),
        tenure_months=req.tenure_months,
        current_savings=req.current_savings,
    )
    try:
        retriever.index_whatif(user_id, sim)
    except Exception:  # noqa: BLE001
        pass

    explanation = None
    if req.explain:
        query = (
            f"Should I buy something for Rs.{req.purchase_amount:,.0f}? "
            f"Compare paying in full vs EMI over {req.tenure_months} months."
        )
        rag = retriever.retrieve(query, user_id)
        result_with_sim = {**result, "whatif_result": sim}
        explanation = explain(query, result_with_sim, rag)

    return {"simulation": sim, "explanation": explanation}


# ---------- Phase 6: voice ----------
# Transcription and synthesis call paid third-party APIs, so both require a
# session; leaving them open is a way to spend someone else's credits.
@app.post("/voice/transcribe")
async def voice_transcribe(_: CurrentUserId, file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    suffix = os.path.splitext(file.filename or "")[1] or ".webm"
    out = voice_service.transcribe(raw, suffix=suffix)
    if not out["available"]:
        raise HTTPException(status_code=503, detail=out["error"])
    # Log the detected speech so it's visible in the server terminal.
    if out.get("error"):
        print(f"[voice] transcription error: {out['error']}", flush=True)
    else:
        print(f"[voice] detected speech: {out.get('text', '')!r}", flush=True)
    return out


class SpeakRequest(BaseModel):
    text: str


@app.post("/voice/speak")
def voice_speak(req: SpeakRequest, _: CurrentUserId):
    audio, error = voice_service.synthesize(req.text)
    if audio is None:
        raise HTTPException(status_code=503, detail=error or "TTS failed")
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg")


@app.get("/voice/config")
def voice_config() -> dict:
    """Voice subsystem capabilities + effective .env configuration (for the UI)."""
    return voice_service.capabilities()


@app.get("/voice/metrics")
def voice_metrics(_: CurrentUserId) -> dict:
    """Observability: STT/TTS latency, fallbacks, provider usage, errors."""
    return voice_service.metrics()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
