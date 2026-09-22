"""AI Personal CFO — FastAPI backend.

Wires the deterministic pipeline (Phases 1-2), RAG (Phase 3), explainer/LLM
(Phase 4), what-if simulator (Phase 5), and voice (Phase 6) behind one API.

Authentication: every endpoint that touches user data resolves the caller from a
bearer token via the ``current_user`` dependency. No endpoint accepts a user id
from the client — that is what made it possible to read or delete anyone's data.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import secrets
import time

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

load_dotenv()

import llm  # noqa: E402
import auth  # noqa: E402
from auth.deps import CurrentUser, CurrentUserId, is_valid_email, normalize_email  # noqa: E402
from agents import llm_client  # noqa: E402
from agents import twin  # noqa: E402
from agents import copilot  # noqa: E402
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
from voice import conversation as voice_conversation  # noqa: E402
from voice import speech as voice_speech  # noqa: E402
from voice import wake as voice_wake  # noqa: E402

logger = logging.getLogger("main")

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
    # Optionally warm up in the background if PRELOAD_MODELS is set
    if os.getenv("PRELOAD_MODELS", "").lower() in ("1", "true", "yes"):
        import threading
        threading.Thread(target=voice_service.preload, daemon=True).start()
        threading.Thread(target=retriever.preload, daemon=True).start()


# ---------- Phase 0 ----------
@app.get("/")
@app.head("/")
def root() -> dict:
    return {"status": "ok", "app": "AI Personal CFO"}


@app.get("/health")
@app.head("/health")
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
        # Archive this upload as well, so it stays browsable after the next one
        # replaces the active snapshot above. `result` has no "workflow" key at
        # this point (it is attached further down), so what lands in the archive
        # matches exactly what /dashboard returns.
        database.save_statement(user_id, result, filename=filename, source_format=fmt)
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


# ---------- Statement history ----------
#
# `results` holds only the active snapshot and is overwritten on every upload.
# These endpoints read the append-only `statements` archive instead, so previous
# statements and their transactions remain reachable.


def _require_statement(statement_id: int, user_id: str) -> dict:
    """Load an archived statement or 404.

    The lookup is scoped by user_id, so a guessed id belonging to another account
    is indistinguishable from one that does not exist.
    """
    record = database.get_statement(statement_id, user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Statement not found.")
    return record


@app.get("/statements")
def statements_index(user_id: CurrentUserId) -> dict:
    """Summaries of every archived statement, newest first (no payloads)."""
    return {"statements": database.list_statements(user_id)}


@app.get("/statements/{statement_id}")
def statement_detail(statement_id: int, user_id: CurrentUserId) -> dict:
    """One archived statement, including its full analysis payload."""
    return _require_statement(statement_id, user_id)


@app.post("/statements/{statement_id}/restore")
def statement_restore(statement_id: int, user_id: CurrentUserId) -> dict:
    """Make an archived statement the active snapshot again.

    Every other panel reads `results` / `transactions`, so this writes the
    archived payload back into both rather than introducing a second code path
    that each panel would have to learn about.

    No new archive row is created: re-activating an old statement is navigation,
    not a new upload.
    """
    payload = _require_statement(statement_id, user_id)["payload"]
    database.save_transactions(user_id, payload.get("transactions", []))
    database.save_result(user_id, payload, record_score=False)
    return payload


@app.delete("/statements/{statement_id}")
def statement_delete(statement_id: int, user_id: CurrentUserId) -> dict:
    if not database.delete_statement(statement_id, user_id):
        raise HTTPException(status_code=404, detail="Statement not found.")
    return {"deleted": True}


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
# Audio arrives as opus/webm at roughly 2 KB per second, so a legitimate spoken
# query is tens of kilobytes. The cap exists to stop an authenticated client from
# posting an arbitrarily large body into a paid STT API.
_MAX_AUDIO_BYTES = 8 * 1024 * 1024

# Whitelist of container suffixes. The uploaded filename is NEVER used to build a
# path -- it only picks an extension for the temp file the STT layer writes, so an
# unexpected value falls back to .webm rather than being trusted.
_ALLOWED_AUDIO_SUFFIXES = frozenset(
    {".webm", ".ogg", ".oga", ".opus", ".wav", ".mp3", ".m4a", ".mp4", ".flac"}
)

# Cap on a client-supplied transcript (the low-latency path in /voice/ask). A
# spoken question is a sentence or two; this only stops an authenticated client
# from pushing a large body straight into the LLM prompt.
_MAX_CLIENT_TRANSCRIPT_CHARS = 1000


def _safe_audio_suffix(filename: str | None) -> str:
    suffix = os.path.splitext(filename or "")[1].lower()
    return suffix if suffix in _ALLOWED_AUDIO_SUFFIXES else ".webm"


@app.post("/voice/transcribe")
async def voice_transcribe(_: CurrentUserId, file: UploadFile = File(...)) -> dict:
    raw = await file.read()
    if len(raw) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip is too large.")
    out = voice_service.transcribe(raw, suffix=_safe_audio_suffix(file.filename))
    if not out["available"]:
        raise HTTPException(status_code=503, detail=out["error"])
    # Transcripts are user speech, so they are logged at debug level only; info
    # records the outcome without the content.
    if out.get("error"):
        logger.warning("voice.transcribe failed: %s", out["error"])
    else:
        logger.info(
            "voice.transcribe ok chars=%d provider=%s",
            len(out.get("text") or ""), out.get("provider"),
        )
        logger.debug("voice.transcribe text=%r", out.get("text", ""))
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


# ---------- Finzo: hands-free voice turn ----------
#
# One round trip for a complete spoken exchange: audio in, spoken answer out.
# Collapsing transcribe + chat + speak into a single call removes two network
# round trips from the path between the user finishing their sentence and hearing
# a reply, which is the latency that decides whether this feels conversational.
#
# The reasoning is NOT reimplemented here. This calls the same
# retriever.retrieve + memory_agent.recall_context + converse() chain that
# POST /chat uses, so a question asked aloud and the same question typed produce
# the same financial answer.


# Every voice turn spends money at a third-party STT API and (usually) an LLM, so
# it is rate limited per account. 40/minute is far above conversational pace
# (a spoken exchange takes seconds) but bounds a runaway client or a stuck
# retry loop. Keyed on user_id, not IP, because the endpoint already requires a
# session and shared NAT would otherwise punish co-located users.
voice_ask_limiter = auth.RateLimiter(max_attempts=40, window_seconds=60)


def _voice_failure(code: str, session=None, **extra) -> dict:
    """Structured, speakable failure. Returned with HTTP 200 on purpose.

    A 4xx/5xx would make the browser's fetch reject, and the frontend would have
    to special-case every code to keep the conversation alive. Returning a normal
    body with ok=false lets the voice loop speak the message and carry on
    listening. Genuine protocol errors (auth, oversized body) still use HTTP
    codes.
    """
    payload = {
        "ok": False,
        "error": {"code": code, "message": voice_speech.error_speech(code)},
        "speech": voice_speech.error_speech(code),
        "transcript": "",
        "response": "",
        **extra,
    }
    if session is not None:
        payload["voice_session_id"] = session.voice_session_id
        payload["conversation_id"] = session.conversation_id
    return payload


def _summarize_conversation_safely(user_id: str, history: list[dict]) -> None:
    """Background memory write. Runs after the response, so it must swallow its
    own errors: there is no client left to report them to."""
    try:
        memory_agent.summarize_conversation(user_id, history)
    except Exception:  # noqa: BLE001
        logger.exception("voice.ask background memory summarise failed")


@app.post("/voice/ask")
async def voice_ask(
    user_id: CurrentUserId,
    background: BackgroundTasks,
    file: UploadFile | None = File(None),
    speak: bool = Form(True),
    timeout_seconds: int = Form(voice_conversation.DEFAULT_TIMEOUT_SECONDS),
    client_transcript: str = Form(""),
) -> dict:
    """Transcribe a spoken query, answer it through the existing CFO pipeline,
    and return both the written answer and speech-ready audio.

    ``client_transcript`` is the fast path. The browser's SpeechRecognition engine
    has already transcribed the query while the user was speaking, at no extra
    latency, so re-decoding the same audio through Whisper costs about a second
    and buys nothing. When the client sends its transcript we skip STT entirely;
    when it cannot (recogniser unsupported, died mid-utterance, or produced
    nothing) it uploads the audio instead and this falls back to the server
    pipeline. Exactly one of the two must be present.
    """
    started = time.monotonic()

    retry_after = voice_ask_limiter.check(user_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many voice requests. Please wait a moment.",
            headers={"Retry-After": str(retry_after)},
        )
    voice_ask_limiter.record_failure(user_id)  # counts every call, not just failures

    client_text = (client_transcript or "").strip()
    # Bound the field: it reaches the LLM prompt, and an unbounded form value is
    # a cheap way to inflate token spend.
    if len(client_text) > _MAX_CLIENT_TRANSCRIPT_CHARS:
        client_text = client_text[:_MAX_CLIENT_TRANSCRIPT_CHARS]

    raw = b""
    if file is not None:
        raw = await file.read()
        if len(raw) > _MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio clip is too large.")
    if not raw and not client_text:
        return _voice_failure("EMPTY_AUDIO")

    if timeout_seconds not in voice_conversation.ALLOWED_TIMEOUTS:
        timeout_seconds = voice_conversation.DEFAULT_TIMEOUT_SECONDS
    session = voice_conversation.registry.get_or_create(
        user_id, timeout_seconds=timeout_seconds
    )

    # ---- speech to text ---------------------------------------------------- #
    if client_text:
        # Fast path: trust the on-device recogniser. Confidence is reported as
        # None rather than a made-up number, since the Web Speech API does not
        # give a comparable score.
        stt = {
            "text": client_text,
            "available": True,
            "error": None,
            "provider": "client_web_speech",
            "confidence": None,
            "language": None,
            "latency_ms": 0,
            "low_confidence": False,
        }
    else:
        stt = voice_service.transcribe(
            raw, suffix=_safe_audio_suffix(file.filename if file else None)
        )
        if not stt.get("available"):
            return _voice_failure("STT_UNAVAILABLE", session)
        if stt.get("error"):
            logger.warning("voice.ask stt error: %s", stt["error"])
            return _voice_failure("STT_FAILED", session)

    transcript = (stt.get("text") or "").strip()
    if not transcript:
        return _voice_failure("NO_SPEECH", session)
    stt_ms = int((time.monotonic() - started) * 1000)

    # ---- barge-in ---------------------------------------------------------- #
    # "Stop" is an instruction to the client, not a question for the LLM.
    if voice_wake.is_stop_command(transcript):
        session.touch()
        logger.info("voice.ask stop command session=%s", session.voice_session_id)
        return {
            "ok": True,
            "action": "stop",
            "transcript": transcript,
            "resolved_query": "",
            "intent": "stop",
            "response": "",
            "speech": "",
            "audio_b64": None,
            "llm_used": False,
            "voice_session_id": session.voice_session_id,
            "conversation_id": session.conversation_id,
        }

    # A wake word spoken in the same breath as the question is stripped so the
    # LLM never sees "finzo how much did i spend".
    query = voice_wake.strip_wake_word(transcript)
    if not query:
        # Bare "Finzo" with no question: acknowledge and keep listening.
        session.touch()
        ack = voice_speech.acknowledgement()
        audio_b64 = None
        if speak:
            audio, _err = voice_service.synthesize(ack)
            audio_b64 = base64.b64encode(audio).decode() if audio else None
        return {
            "ok": True,
            "action": "acknowledge",
            "transcript": transcript,
            "resolved_query": "",
            "intent": "wake",
            "response": ack,
            "speech": ack,
            "audio_b64": audio_b64,
            "llm_used": False,
            "voice_session_id": session.voice_session_id,
            "conversation_id": session.conversation_id,
        }

    # ---- follow-up resolution (deterministic, before the LLM) -------------- #
    resolved_query = session.resolve(query)

    # ---- the existing CFO pipeline, unchanged ------------------------------ #
    result = database.get_result(user_id)
    if result is None:
        return _voice_failure("NO_DATA", session, transcript=transcript)

    try:
        history = database.get_conversation(user_id, limit=20)
        rag = retriever.retrieve(resolved_query, user_id)
        memory_context = memory_agent.recall_context(user_id)
        answer = converse(
            resolved_query, result, rag, history, memory_context=memory_context
        )
    except Exception:  # noqa: BLE001
        logger.exception("voice.ask pipeline failed session=%s", session.voice_session_id)
        session.note_turn(
            text=transcript, resolved_text=resolved_query, intent="unknown",
            response="", duration_ms=int((time.monotonic() - started) * 1000),
            status="error",
        )
        return _voice_failure("LLM_FAILED", session, transcript=transcript)

    written = answer.get("response") or ""
    intent = answer.get("intent") or "spending"

    # Voice answers stay short; the written form still goes to the transcript
    # panel, so nothing is lost.
    speech_text = voice_speech.for_speech(written, max_sentences=4)

    # Persist through the same history the text copilot uses, so switching
    # between voice and typing keeps one continuous conversation.
    database.save_message(user_id, "user", resolved_query)
    database.save_message(
        user_id, "assistant", written,
        intent=intent, llm_used=answer.get("llm_used"),
    )

    # Memory summarisation embeds text into Chroma, which costs a few hundred
    # milliseconds. Nothing in this response depends on it, and the next turn
    # reads memory from the database rather than from this call, so it runs after
    # the response is sent instead of making the user wait for it.
    background.add_task(
        _summarize_conversation_safely,
        user_id,
        history + [{"role": "user", "content": resolved_query}],
    )

    duration_ms = int((time.monotonic() - started) * 1000)
    session.note_turn(
        text=transcript, resolved_text=resolved_query, intent=intent,
        response=written, duration_ms=duration_ms,
    )

    # ---- text to speech ---------------------------------------------------- #
    audio_b64: str | None = None
    tts_error: str | None = None
    if speak and speech_text:
        audio, tts_error = voice_service.synthesize(speech_text)
        if audio:
            audio_b64 = base64.b64encode(audio).decode()
        else:
            # A TTS failure must not lose the answer: the client shows the text
            # and the conversation continues.
            logger.warning("voice.ask tts failed: %s", tts_error)

    logger.info(
        "voice.ask ok session=%s intent=%s llm=%s stt=%s stt_ms=%d ms=%d spoken=%s",
        session.voice_session_id, intent, answer.get("llm_used"),
        stt.get("provider"), stt_ms, duration_ms, audio_b64 is not None,
    )

    return {
        "ok": True,
        "action": "answer",
        "transcript": transcript,
        "resolved_query": resolved_query,
        "intent": intent,
        "response": written,
        "speech": speech_text,
        "audio_b64": audio_b64,
        "tts_error": tts_error,
        "llm_used": bool(answer.get("llm_used")),
        "retrieved_context": answer.get("retrieved_context", []),
        "confidence": stt.get("confidence"),
        "low_confidence": stt.get("low_confidence"),
        "stt_provider": stt.get("provider"),
        "language": stt.get("language"),
        "duration_ms": duration_ms,
        "stt_ms": stt_ms,
        "voice_session_id": session.voice_session_id,
        "conversation_id": session.conversation_id,
        "context": {
            "current_topic": session.current_topic,
            "last_category": session.last_category,
            "last_metric": session.last_metric,
        },
    }


# ---------- Finzo: streaming voice turn ----------
#
# Same pipeline as POST /voice/ask, delivered as Server-Sent Events so the client
# can start speaking the first sentence while the rest of the answer is still
# being generated. On a two-second answer that is most of the wait removed: the
# user hears "You spent 6,840 rupees on food this month." while the explanation
# behind it is still arriving.
#
# Why SSE and not a WebSocket: the traffic is one request in, many chunks out,
# with no client-to-server messages mid-turn. SSE covers that over plain HTTP,
# inherits the existing bearer-token auth, and needs no connection lifecycle to
# manage. A WebSocket would add both without being used.
#
# Why POST rather than EventSource: EventSource cannot set an Authorization
# header. The client reads the stream from fetch() instead.


def _sse(event: str, payload: dict) -> str:
    """Format one Server-Sent Event.

    json.dumps matters here: an answer containing a newline would otherwise be
    read as a frame boundary and truncate the event.
    """
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


@app.post("/voice/ask/stream")
async def voice_ask_stream(
    user_id: CurrentUserId,
    background: BackgroundTasks,
    file: UploadFile | None = File(None),
    timeout_seconds: int = Form(voice_conversation.DEFAULT_TIMEOUT_SECONDS),
    client_transcript: str = Form(""),
    max_spoken_sentences: int = Form(4),
) -> StreamingResponse:
    """Stream a spoken turn: transcript, then answer text, then speech chunks.

    Event sequence:
      ``meta``   once   - transcript, resolved query, intent, session ids
      ``action`` once   - "stop" or "acknowledge"; terminal, no answer follows
      ``delta``  many   - raw answer text for the on-screen transcript
      ``speak``  many   - one complete speech-ready sentence, in order
      ``done``   once   - full answer plus timings
      ``error``  once   - terminal; carries a speakable message

    Never emits TTS audio: the client speaks each ``speak`` chunk with the local
    voice as it arrives. Waiting on server-side synthesis per sentence would
    reintroduce the latency this endpoint exists to remove.
    """
    started = time.monotonic()

    # Validation and rate limiting happen before the response starts, so these
    # still surface as real HTTP status codes. Once the stream is open the headers
    # are already sent and every failure has to become an `error` event instead.
    retry_after = voice_ask_limiter.check(user_id)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many voice requests. Please wait a moment.",
            headers={"Retry-After": str(retry_after)},
        )
    voice_ask_limiter.record_failure(user_id)

    client_text = (client_transcript or "").strip()[:_MAX_CLIENT_TRANSCRIPT_CHARS]
    raw = b""
    if file is not None:
        raw = await file.read()
        if len(raw) > _MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio clip is too large.")

    if timeout_seconds not in voice_conversation.ALLOWED_TIMEOUTS:
        timeout_seconds = voice_conversation.DEFAULT_TIMEOUT_SECONDS
    filename = file.filename if file else None

    async def events():
        def fail(code: str) -> str:
            return _sse("error", {"code": code, "message": voice_speech.error_speech(code)})

        if not raw and not client_text:
            yield fail("EMPTY_AUDIO")
            return

        session = voice_conversation.registry.get_or_create(
            user_id, timeout_seconds=timeout_seconds
        )

        # ---- transcript ---------------------------------------------------- #
        if client_text:
            transcript, stt_provider = client_text, "client_web_speech"
        else:
            stt = voice_service.transcribe(raw, suffix=_safe_audio_suffix(filename))
            if not stt.get("available"):
                yield fail("STT_UNAVAILABLE")
                return
            if stt.get("error"):
                logger.warning("voice.ask.stream stt error: %s", stt["error"])
                yield fail("STT_FAILED")
                return
            transcript = (stt.get("text") or "").strip()
            stt_provider = stt.get("provider") or "unknown"
        if not transcript:
            yield fail("NO_SPEECH")
            return
        stt_ms = int((time.monotonic() - started) * 1000)

        # ---- barge-in and bare wake word ----------------------------------- #
        if voice_wake.is_stop_command(transcript):
            session.touch()
            yield _sse("action", {"action": "stop", "transcript": transcript})
            return

        query = voice_wake.strip_wake_word(transcript)
        if not query:
            session.touch()
            ack = voice_speech.acknowledgement()
            yield _sse(
                "action",
                {"action": "acknowledge", "transcript": transcript, "speech": ack},
            )
            return

        resolved_query = session.resolve(query)

        result = database.get_result(user_id)
        if result is None:
            yield fail("NO_DATA")
            return

        # ---- prompt assembly (same path as the text copilot) --------------- #
        try:
            history = database.get_conversation(user_id, limit=20)
            rag = retriever.retrieve(resolved_query, user_id)
            memory_context = memory_agent.recall_context(user_id)
            turn = copilot.prepare_turn(
                resolved_query, result, rag, history, memory_context=memory_context
            )
        except Exception:  # noqa: BLE001
            logger.exception("voice.ask.stream prep failed")
            yield fail("LLM_FAILED")
            return

        yield _sse(
            "meta",
            {
                "transcript": transcript,
                "resolved_query": resolved_query,
                "intent": turn["intent"],
                "stt_provider": stt_provider,
                "stt_ms": stt_ms,
                "voice_session_id": session.voice_session_id,
                "conversation_id": session.conversation_id,
            },
        )

        # ---- stream the answer --------------------------------------------- #
        streamer = voice_speech.SentenceStreamer(max_sentences=max_spoken_sentences)
        written = ""
        llm_used = False
        try:
            async for chunk in llm_router.stream(
                [Message(role="user", content=turn["prompt"])]
            ):
                if not chunk:
                    continue
                written += chunk
                llm_used = True
                yield _sse("delta", {"text": chunk})
                for sentence in streamer.feed(chunk):
                    yield _sse("speak", {"text": sentence})
        except Exception as exc:  # noqa: BLE001
            # Mid-stream failure. If some of the answer already went out, keep it
            # and close cleanly; the user heard a partial but correct answer.
            logger.warning("voice.ask.stream llm failed: %s", exc)
            if not written.strip():
                # Nothing was said yet, so fall back to the deterministic answer
                # rather than leaving the user with silence.
                written, llm_used = turn["fallback"], False
                yield _sse("delta", {"text": written})
                for sentence in streamer.feed(written):
                    yield _sse("speak", {"text": sentence})

        for sentence in streamer.flush():
            yield _sse("speak", {"text": sentence})

        # ---- persist ------------------------------------------------------- #
        written = written.strip()
        duration_ms = int((time.monotonic() - started) * 1000)
        try:
            database.save_message(user_id, "user", resolved_query)
            database.save_message(
                user_id, "assistant", written, intent=turn["intent"], llm_used=llm_used
            )
            session.note_turn(
                text=transcript, resolved_text=resolved_query, intent=turn["intent"],
                response=written, duration_ms=duration_ms,
            )
            background.add_task(
                _summarize_conversation_safely,
                user_id,
                history + [{"role": "user", "content": resolved_query}],
            )
        except Exception:  # noqa: BLE001
            # The answer was already delivered and spoken; a persistence problem
            # must not turn a successful turn into an error.
            logger.exception("voice.ask.stream persist failed")

        logger.info(
            "voice.ask.stream ok session=%s intent=%s stt=%s stt_ms=%d ms=%d",
            session.voice_session_id, turn["intent"], stt_provider, stt_ms, duration_ms,
        )
        yield _sse(
            "done",
            {
                "response": written,
                "speech": voice_speech.for_speech(
                    written, max_sentences=max_spoken_sentences
                ),
                "intent": turn["intent"],
                "llm_used": llm_used,
                "retrieved_context": turn["sources"],
                "duration_ms": duration_ms,
                "stt_ms": stt_ms,
            },
        )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        # Without this an nginx/Render proxy will buffer the whole stream and
        # deliver it as one blob, silently undoing the streaming.
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/voice/session")
def voice_session(user_id: CurrentUserId) -> dict:
    """Current hands-free session state (no audio is ever stored)."""
    session = voice_conversation.registry.peek(user_id)
    return {"session": session.snapshot() if session else None}


@app.delete("/voice/session")
def voice_session_end(user_id: CurrentUserId) -> dict:
    """End conversation mode and forget dialogue context."""
    return {"ended": voice_conversation.registry.end(user_id)}


@app.get("/voice/wake-config")
def voice_wake_config() -> dict:
    """Wake-word settings the frontend needs to match server-side behaviour."""
    return {
        "wake_word": voice_wake.WAKE_WORD,
        "acknowledgements": list(voice_speech.ACKNOWLEDGEMENTS),
        "timeout_options": list(voice_conversation.ALLOWED_TIMEOUTS),
        "default_timeout": voice_conversation.DEFAULT_TIMEOUT_SECONDS,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
