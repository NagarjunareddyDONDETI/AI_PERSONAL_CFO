"""POST /voice/ask -- the single-round-trip hands-free voice turn.

STT, the LLM and TTS are all patched, so these tests assert on the endpoint's own
behaviour: validation, error shape, wake-word stripping, barge-in, follow-up
resolution, session handling and graceful degradation. The point of the feature is
that a spoken question and a typed question take the SAME reasoning path, so there
is a test asserting exactly that.
"""
from __future__ import annotations

import itertools
import os

import pytest

os.environ.setdefault("AUTH_SECRET", "test-secret-long-enough-for-the-length-check-0123")

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from db import database  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient on a throwaway database (see test_api_auth for why _DB_PATH
    is patched on the module rather than through the environment)."""
    original = database._DB_PATH
    database._DB_PATH = str(tmp_path_factory.mktemp("voiceask") / "va.db")
    import main

    assert database._DB_PATH != original, "test database path was not applied"
    with fastapi_testclient.TestClient(main.app) as c:
        c.app_module = main  # type: ignore[attr-defined]
        yield c
    database._DB_PATH = original


_counter = itertools.count()


@pytest.fixture
def main_mod(client):
    return client.app_module  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _reset_state(main_mod):
    main_mod.auth.register_limiter.clear()
    main_mod.auth.login_limiter.clear()
    main_mod.voice_ask_limiter.clear()
    yield
    main_mod.voice_ask_limiter.clear()


@pytest.fixture
def account(client, main_mod):
    """A registered user with an analysed statement already stored."""
    email = f"finzo-{next(_counter)}@example.com"
    res = client.post(
        "/auth/register", json={"email": email, "password": "a good long password"}
    )
    assert res.status_code == 201, res.text
    session = res.json()
    user_id = session["user"]["user_id"]

    database.save_result(
        user_id,
        {
            "user_id": user_id,
            "transactions": [
                {"date": "2026-08-02", "description": "Swiggy", "amount": -4850.0,
                 "category": "Food"},
                {"date": "2026-08-03", "description": "Amazon", "amount": -8200.0,
                 "category": "Shopping"},
            ],
            "monthly_summary": {
                "months": ["2026-08"],
                "category_totals": {"Food": 4850.0, "Shopping": 8200.0},
                "by_month_category": {"2026-08": {"Food": 4850.0}},
                "monthly_income": {"2026-08": 50000.0},
                "monthly_expenses": {"2026-08": 13050.0},
            },
            "anomalies": [],
            "forecast": {"next_month": "2026-09", "total_expense_forecast": 13000.0,
                         "category_forecast": {}, "history": {"months": [], "expenses": []}},
            "health_score": {"score": 72, "rating": "Good", "savings_rate": 0.22,
                             "income": 50000.0, "expenses": 13050.0,
                             "anomalies_count": 0, "emergency_fund_months": 3.0,
                             "active_emis": 0, "reference_month": "2026-08"},
            "savings_suggestions": [],
        },
        record_score=False,
    )
    return {"headers": {"Authorization": f"Bearer {session['access_token']}"},
            "user_id": user_id}


def _audio(size: int = 2048) -> dict:
    """A dummy multipart audio payload. Content is irrelevant: STT is patched."""
    return {"file": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * size, "audio/webm")}


@pytest.fixture
def stub_pipeline(main_mod, monkeypatch):
    """Patch STT / LLM / TTS. Returns a dict so tests can tune the behaviour."""
    state = {
        "transcript": "how much did i spend on food",
        "stt_available": True,
        "stt_error": None,
        "answer": "You spent **Rs.4,850** on food last month.",
        "llm_used": True,
        "tts_audio": b"ID3fake-mp3-bytes",
        "tts_error": None,
        "converse_calls": [],
    }

    def fake_transcribe(raw, suffix=".webm"):
        return {
            "text": state["transcript"], "available": state["stt_available"],
            "error": state["stt_error"], "bytes": len(raw), "provider": "fake",
            "confidence": 0.9, "language": "en", "latency_ms": 12,
            "low_confidence": False,
        }

    def fake_synthesize(text):
        return state["tts_audio"], state["tts_error"]

    def fake_converse(query, result, rag, history=None, memory_context=""):
        state["converse_calls"].append(query)
        from orchestrator.intent_router import route_intent
        return {"response": state["answer"], "intent": route_intent(query),
                "retrieved_context": [], "llm_used": state["llm_used"]}

    monkeypatch.setattr(main_mod.voice_service, "transcribe", fake_transcribe)
    monkeypatch.setattr(main_mod.voice_service, "synthesize", fake_synthesize)
    monkeypatch.setattr(main_mod, "converse", fake_converse)
    monkeypatch.setattr(main_mod.retriever, "retrieve",
                        lambda q, uid: {"context": "", "sources": []})
    monkeypatch.setattr(main_mod.memory_agent, "recall_context", lambda uid: "")
    monkeypatch.setattr(main_mod.memory_agent, "summarize_conversation",
                        lambda uid, h: 0)
    return state


# ---- auth ----------------------------------------------------------------- #
def test_voice_ask_requires_authentication(client):
    res = client.post("/voice/ask", files=_audio())
    assert res.status_code in (401, 403)


def test_voice_session_requires_authentication(client):
    assert client.get("/voice/session").status_code in (401, 403)


def test_wake_config_is_public(client):
    res = client.get("/voice/wake-config")
    assert res.status_code == 200
    assert res.json()["wake_word"] == "finzo"


# ---- happy path ----------------------------------------------------------- #
def test_successful_voice_turn(client, account, stub_pipeline):
    res = client.post("/voice/ask", headers=account["headers"], files=_audio(),
                      data={"speak": "true"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    assert body["action"] == "answer"
    assert body["transcript"] == "how much did i spend on food"
    assert body["intent"] == "spending"
    assert body["llm_used"] is True
    assert body["voice_session_id"].startswith("vs_")
    assert body["conversation_id"].startswith("vc_")


def test_answer_is_shaped_for_speech(client, account, stub_pipeline):
    """Markdown must not reach TTS, and Rs. must become a spoken word."""
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    body = res.json()
    assert "**" not in body["speech"]
    assert "4,850 rupees" in body["speech"]
    # The written form is preserved for the transcript panel.
    assert "**" in body["response"]


def test_audio_returned_as_base64_when_speak_true(client, account, stub_pipeline):
    import base64

    res = client.post("/voice/ask", headers=account["headers"], files=_audio(),
                      data={"speak": "true"})
    body = res.json()
    assert body["audio_b64"]
    assert base64.b64decode(body["audio_b64"]) == b"ID3fake-mp3-bytes"


def test_no_audio_when_speak_false(client, account, stub_pipeline):
    res = client.post("/voice/ask", headers=account["headers"], files=_audio(),
                      data={"speak": "false"})
    assert res.json()["audio_b64"] is None


def test_turn_is_persisted_to_shared_chat_history(client, account, stub_pipeline):
    """Voice and text must share one conversation, not two parallel ones."""
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    history = client.get("/chat/history", headers=account["headers"]).json()["history"]
    assert [m["role"] for m in history[-2:]] == ["user", "assistant"]
    assert history[-1]["intent"] == "spending"


def test_voice_uses_the_same_converse_pipeline(client, account, stub_pipeline):
    """Rule 3/4: no separate reasoning path for voice."""
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    assert stub_pipeline["converse_calls"], "converse() was not called"
    assert stub_pipeline["converse_calls"][-1] == "how much did i spend on food"


# ---- wake word in the same breath ----------------------------------------- #
def test_wake_word_is_stripped_before_the_llm(client, account, stub_pipeline):
    stub_pipeline["transcript"] = "Finzo, how much did I spend on food?"
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    sent = stub_pipeline["converse_calls"][-1]
    assert "finzo" not in sent.lower(), f"wake word leaked into the query: {sent!r}"
    assert "spend" in sent


def test_bare_wake_word_acknowledges_without_calling_the_llm(
    client, account, stub_pipeline
):
    stub_pipeline["transcript"] = "Finzo"
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    body = res.json()
    assert body["ok"] is True
    assert body["action"] == "acknowledge"
    assert body["speech"]
    assert stub_pipeline["converse_calls"] == [], "no LLM call for a bare wake word"


# ---- barge-in ------------------------------------------------------------- #
@pytest.mark.parametrize("said", ["stop", "Stop.", "wait", "cancel", "Finzo stop"])
def test_stop_command_short_circuits(client, account, stub_pipeline, said):
    stub_pipeline["transcript"] = said
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    body = res.json()
    assert body["action"] == "stop"
    assert stub_pipeline["converse_calls"] == [], "stop must not reach the LLM"


def test_question_containing_stop_is_still_answered(client, account, stub_pipeline):
    stub_pipeline["transcript"] = "how do I stop overspending"
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    assert res.json()["action"] == "answer"


# ---- follow-up context ---------------------------------------------------- #
def test_follow_up_is_resolved_before_reaching_the_llm(
    client, account, stub_pipeline
):
    """Scenario 4: 'food' then 'what about shopping?'"""
    stub_pipeline["transcript"] = "how much did i spend on food"
    client.post("/voice/ask", headers=account["headers"], files=_audio())

    stub_pipeline["transcript"] = "what about shopping"
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    sent = stub_pipeline["converse_calls"][-1]
    assert "Shopping" in sent, f"follow-up not resolved: {sent!r}"
    assert res.json()["resolved_query"] == sent
    assert res.json()["context"]["last_category"] == "Shopping"


def test_why_follow_up_carries_the_topic(client, account, stub_pipeline):
    stub_pipeline["transcript"] = "how much did i spend on food"
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    stub_pipeline["transcript"] = "why"
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    assert "Food" in stub_pipeline["converse_calls"][-1]


def test_session_is_reported_and_can_be_ended(client, account, stub_pipeline):
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    got = client.get("/voice/session", headers=account["headers"]).json()["session"]
    assert got["turns"], "the turn log should not be empty"
    assert got["last_category"] == "Food"

    assert client.delete("/voice/session", headers=account["headers"]).json()["ended"]
    assert client.get("/voice/session", headers=account["headers"]).json()["session"] is None


def test_session_snapshot_contains_no_audio(client, account, stub_pipeline):
    client.post("/voice/ask", headers=account["headers"], files=_audio())
    raw = client.get("/voice/session", headers=account["headers"]).text.lower()
    assert "audio_b64" not in raw
    assert "webm" not in raw


# ---- validation and failure modes ----------------------------------------- #
def test_empty_audio_is_rejected_gracefully(client, account, stub_pipeline):
    res = client.post("/voice/ask", headers=account["headers"],
                      files={"file": ("c.webm", b"", "audio/webm")})
    assert res.status_code == 200, "must stay conversational, not throw"
    body = res.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "EMPTY_AUDIO"
    assert body["speech"]


def test_oversized_audio_is_rejected(client, account, stub_pipeline, main_mod):
    big = b"\x00" * (main_mod._MAX_AUDIO_BYTES + 1)
    res = client.post("/voice/ask", headers=account["headers"],
                      files={"file": ("c.webm", big, "audio/webm")})
    assert res.status_code == 413


def test_no_speech_detected(client, account, stub_pipeline):
    stub_pipeline["transcript"] = "   "
    body = client.post("/voice/ask", headers=account["headers"], files=_audio()).json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NO_SPEECH"


def test_stt_unavailable(client, account, stub_pipeline):
    stub_pipeline["stt_available"] = False
    body = client.post("/voice/ask", headers=account["headers"], files=_audio()).json()
    assert body["error"]["code"] == "STT_UNAVAILABLE"


def test_stt_error(client, account, stub_pipeline):
    stub_pipeline["stt_error"] = "network unreachable"
    body = client.post("/voice/ask", headers=account["headers"], files=_audio()).json()
    assert body["error"]["code"] == "STT_FAILED"


def test_pipeline_exception_is_contained(client, account, stub_pipeline, main_mod,
                                         monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("gemini exploded")

    monkeypatch.setattr(main_mod, "converse", boom)
    res = client.post("/voice/ask", headers=account["headers"], files=_audio())
    assert res.status_code == 200
    body = res.json()
    assert body["error"]["code"] == "LLM_FAILED"
    assert "AI service" in body["speech"]


def test_tts_failure_still_returns_the_answer(client, account, stub_pipeline):
    """Rule: a TTS failure must not lose the answer."""
    stub_pipeline["tts_audio"] = None
    stub_pipeline["tts_error"] = "gtts offline"
    body = client.post("/voice/ask", headers=account["headers"], files=_audio()).json()
    assert body["ok"] is True
    assert body["audio_b64"] is None
    assert body["response"], "the text answer must survive a TTS failure"
    assert body["tts_error"] == "gtts offline"


def test_no_statement_uploaded_yet(client, main_mod, stub_pipeline):
    res = client.post("/auth/register",
                      json={"email": f"nodata-{next(_counter)}@example.com",
                            "password": "a good long password"})
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    body = client.post("/voice/ask", headers=headers, files=_audio()).json()
    assert body["ok"] is False
    assert body["error"]["code"] == "NO_DATA"


def test_unknown_file_suffix_falls_back_safely(client, account, stub_pipeline):
    """A hostile filename must not choose the temp-file extension."""
    res = client.post(
        "/voice/ask", headers=account["headers"],
        files={"file": ("../../etc/passwd.exe", b"\x00" * 64, "audio/webm")},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_invalid_timeout_falls_back_to_default(client, account, stub_pipeline,
                                               main_mod):
    from voice.conversation import DEFAULT_TIMEOUT_SECONDS

    client.post("/voice/ask", headers=account["headers"], files=_audio(),
                data={"timeout_seconds": "99999"})
    got = client.get("/voice/session", headers=account["headers"]).json()["session"]
    assert got["timeout_seconds"] == DEFAULT_TIMEOUT_SECONDS


def test_rate_limited_after_the_cap(client, account, stub_pipeline, main_mod):
    limit = main_mod.voice_ask_limiter.max_attempts
    codes = [
        client.post("/voice/ask", headers=account["headers"], files=_audio()).status_code
        for _ in range(limit + 2)
    ]
    assert 429 in codes, "voice turns must be rate limited"


def test_degrades_when_llm_not_configured(client, account, stub_pipeline):
    """No Gemini key: still answers, marked as computed rather than generated."""
    stub_pipeline["llm_used"] = False
    stub_pipeline["answer"] = "Your score is 72. (LLM not configured.)"
    body = client.post("/voice/ask", headers=account["headers"], files=_audio()).json()
    assert body["ok"] is True
    assert body["llm_used"] is False
    assert "72" in body["speech"]
