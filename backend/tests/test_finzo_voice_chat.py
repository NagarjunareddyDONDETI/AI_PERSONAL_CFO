"""POST /finzo/voice/chat, the health and hands-free status endpoints, and the
end-to-end spoken food question.

The end-to-end test uses the REAL STT and TTS registries, the real Voicebox
client and providers (Voicebox itself is mocked at the HTTP layer), the real
voice_ask -> converse pipeline, and a stored analysis. Only the LLM is replaced,
by a fake that can only repeat figures present in the prompt it is given. That
proves the spoken number came from the computed data, not from the model.
"""
from __future__ import annotations

import base64
import io
import itertools
import json
import os
import re
import time
import wave

import pytest
import respx

os.environ.setdefault("AUTH_SECRET", "test-secret-long-enough-for-the-length-check-0123")

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from db import database  # noqa: E402
from voice.tts.base import TTSResult  # noqa: E402

VOICEBOX = "http://127.0.0.1:17493"


def wav_bytes(seconds: float = 0.6, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x10\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    original = database._DB_PATH
    database._DB_PATH = str(tmp_path_factory.mktemp("finzovoice") / "fv.db")
    import main

    assert database._DB_PATH != original
    with fastapi_testclient.TestClient(main.app) as c:
        c.app_module = main  # type: ignore[attr-defined]
        yield c
    database._DB_PATH = original


@pytest.fixture
def main_mod(client):
    return client.app_module  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _isolate(main_mod, monkeypatch, tmp_path):
    main_mod.auth.register_limiter.clear()
    main_mod.voice_ask_limiter.clear()
    monkeypatch.setenv("FINZO_VOICE_STATE_DIR", str(tmp_path / "state"))
    # No test may reach a real vector store, memory writer or network TTS.
    monkeypatch.setattr(main_mod.retriever, "retrieve", lambda q, uid: {"context": "", "sources": []})
    monkeypatch.setattr(main_mod.memory_agent, "recall_context", lambda uid: "")
    monkeypatch.setattr(main_mod.memory_agent, "summarize_conversation", lambda uid, h: None)
    yield
    main_mod.voice_ask_limiter.clear()


_counter = itertools.count()


def _register(client) -> dict:
    email = f"voicechat-{next(_counter)}@example.com"
    res = client.post("/auth/register", json={"email": email, "password": "a good long password"})
    assert res.status_code == 201, res.text
    body = res.json()
    return {"headers": {"Authorization": f"Bearer {body['access_token']}"},
            "user_id": body["user"]["user_id"]}


@pytest.fixture
def account(client):
    acct = _register(client)
    uid = acct["user_id"]
    database.save_result(
        uid,
        {
            "user_id": uid,
            "transactions": [
                {"date": "2026-08-02", "description": "Swiggy", "amount": -2600.0, "category": "Food"},
                {"date": "2026-08-09", "description": "Zomato", "amount": -2250.0, "category": "Food"},
                {"date": "2026-08-03", "description": "Amazon", "amount": -8200.0, "category": "Shopping"},
            ],
            "monthly_summary": {
                "months": ["2026-07", "2026-08"],
                "category_totals": {"Food": 8830.0, "Shopping": 8200.0},
                "by_month_category": {"2026-07": {"Food": 3980.0}, "2026-08": {"Food": 4850.0}},
                "monthly_income": {"2026-08": 50000.0},
                "monthly_expenses": {"2026-08": 13050.0},
            },
            "anomalies": [],
            "forecast": {"next_month": "2026-09", "total_expense_forecast": 13000.0,
                         "category_forecast": {}, "history": {"months": [], "expenses": []}},
            "health_score": {"score": 72, "rating": "Good", "savings_rate": 0.22, "income": 50000.0,
                             "expenses": 13050.0, "anomalies_count": 0, "emergency_fund_months": 3.0,
                             "active_emis": 0, "reference_month": "2026-08"},
            "savings_suggestions": [],
        },
        record_score=False,
    )
    return acct


@pytest.fixture
def fake_llm(monkeypatch):
    """An 'LLM' that can only speak figures it was given in the prompt."""
    from agents import llm_client

    calls: list[str] = []

    def generate(prompt: str) -> str:
        calls.append(prompt)
        data = prompt.split("Computed financial data", 1)[1]
        food = json.loads(re.search(r"\{.*\}", data, re.DOTALL).group(0))
        aug = food["monthly_summary"]["by_month_category"]["2026-08"]["Food"]
        jul = food["monthly_summary"]["by_month_category"]["2026-07"]["Food"]
        return (f"You spent **₹{aug:,.0f}** on food this month, "
                f"which is ₹{aug - jul:,.0f} more than last month.")

    monkeypatch.setattr(llm_client, "is_configured", lambda: True)
    monkeypatch.setattr(llm_client, "generate", generate)
    return calls


@pytest.fixture
def voicebox_up(monkeypatch):
    """Point the process-wide Voicebox client at a mocked, healthy server."""
    from voice.voicebox import VoiceboxClient, VoiceboxConfig
    from voice.voicebox import client as vb_module

    vb = VoiceboxClient(VoiceboxConfig(enabled=True, base_url=VOICEBOX, voice_id="Finzo",
                                       health_ttl_seconds=600))
    vb._health_cache = (time.monotonic(), {"ok": True, "status": "healthy"})
    monkeypatch.setattr(vb_module, "_client", vb)
    return vb


# --------------------------------------------------------------------------- #
# end to end
# --------------------------------------------------------------------------- #
def test_e2e_spoken_food_question(client, account, fake_llm, voicebox_up):
    """audio -> transcript -> intent -> stored data -> answer -> Voicebox -> playable WAV."""
    spoken = wav_bytes(1.5, 16000)
    with respx.mock(base_url=VOICEBOX, assert_all_called=True) as vb:
        stt = vb.post("/transcribe").respond(
            200, json={"text": "How much did I spend on food this month?", "duration": 1.5}
        )
        vb.get("/profiles").respond(200, json=[{"id": "p-finzo", "name": "Finzo", "language": "en"}])
        tts = vb.post("/generate/stream").respond(200, content=wav_bytes(), headers={"content-type": "audio/wav"})

        res = client.post(
            "/finzo/voice/chat",
            headers=account["headers"],
            files={"file": ("question.webm", spoken, "audio/webm")},
        )

    assert res.status_code == 200, res.text
    body = res.json()
    # 1. audio reached Voicebox STT, and its transcript was used
    assert stt.call_count == 1
    assert body["stt_provider"] == "voicebox"
    assert body["transcript"] == "How much did I spend on food this month?"
    # 2. the existing intent router and data slice ran
    assert body["intent"] == "spending"
    assert '"Food": 4850.0' in fake_llm[0], "stored figure was not in the LLM prompt"
    # 3. the answer carries the computed figures, verbatim
    assert "4,850" in body["response"] and "870" in body["response"]
    # 4. speech is shaped for listening: no markdown, currency spoken
    assert body["speech"] == "You spent 4,850 rupees on food this month, which is 870 rupees more than last month."
    # 5. Voicebox spoke exactly that text, with no persona rewrite
    sent = json.loads(tts.calls.last.request.content)
    assert sent["text"] == body["speech"]
    assert sent["personality"] is False and sent["profile_id"] == "p-finzo"
    # 6. the audio returned to the browser is a playable WAV
    assert body["tts_provider"] == "voicebox" and body["audio_mime"] == "audio/wav"
    with wave.open(io.BytesIO(base64.b64decode(body["audio_b64"]))) as w:
        assert w.getnframes() / w.getframerate() > 0.5


def test_follow_up_uses_conversation_context(client, account, fake_llm, voicebox_up, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod.voice_service, "synthesize_result",
                        lambda t: TTSResult(audio=wav_bytes(), mime="audio/wav", provider="voicebox"))
    first = client.post("/finzo/voice/chat", headers=account["headers"],
                        data={"transcript": "how much did i spend on food"})
    assert first.status_code == 200 and first.json()["ok"]

    # "What about last month?" is rewritten deterministically to keep the food
    # topic, and the history still reaches the model as well.
    second = client.post("/finzo/voice/chat", headers=account["headers"],
                         data={"transcript": "what about last month"}).json()
    assert second["ok"]
    assert second["resolved_query"] == "How much did I spend on Food last month?"
    history = fake_llm[-1].split("Conversation so far:", 1)[1].split("Retrieved", 1)[0]
    assert "how much did i spend on food" in history.lower()

    # "Why did it increase?" IS rewritten deterministically, before any LLM.
    third = client.post("/finzo/voice/chat", headers=account["headers"],
                        data={"transcript": "why did it increase"}).json()
    assert third["ok"]
    assert "food" in third["resolved_query"].lower() and "why" in third["resolved_query"].lower()


def test_deterministic_answer_without_any_llm(client, account, main_mod, monkeypatch):
    """No LLM at all: the answer is the computed data itself, never a guess."""
    from agents import llm_client

    monkeypatch.setattr(llm_client, "is_configured", lambda: False)
    monkeypatch.setattr(main_mod.voice_service, "synthesize_result",
                        lambda t: TTSResult(provider="none", error="off"))
    body = client.post("/finzo/voice/chat", headers=account["headers"],
                       data={"transcript": "how much did i spend on food this month"}).json()
    assert body["ok"] and body["llm_used"] is False
    assert "4850" in body["response"]


# --------------------------------------------------------------------------- #
# failure handling
# --------------------------------------------------------------------------- #
def test_voicebox_unavailable_still_answers(client, account, fake_llm, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod.voice_service, "synthesize_result",
                        lambda t: TTSResult(provider="voicebox", error="VOICEBOX_UNAVAILABLE: refused"))
    res = client.post("/finzo/voice/chat", headers=account["headers"],
                      data={"transcript": "how much did i spend on food"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] and "4,850" in body["response"]
    assert body["audio_b64"] is None and "VOICEBOX_UNAVAILABLE" in body["tts_error"]


def test_invalid_audio_gets_a_spoken_apology(client, account, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod.voice_service, "transcribe", lambda raw, suffix=".webm": {
        "text": "", "available": True, "error": "Error opening audio", "provider": "voicebox"})
    monkeypatch.setattr(main_mod.voice_service, "synthesize_result",
                        lambda t: TTSResult(audio=b"ID3x", provider="gtts"))
    res = client.post("/finzo/voice/chat", headers=account["headers"],
                      files={"file": ("q.webm", b"definitely not audio" * 50, "audio/webm")})
    body = res.json()
    assert res.status_code == 200 and body["ok"] is False
    assert body["error"]["code"] == "STT_FAILED"
    assert body["speech"] and body["audio_b64"]  # the apology is spoken
    assert "Traceback" not in json.dumps(body)


def test_nothing_sent(client, account):
    body = client.post("/finzo/voice/chat", headers=account["headers"], data={}).json()
    assert body["ok"] is False and body["error"]["code"] == "EMPTY_AUDIO"


def test_financial_tool_failure_is_graceful(client, account, main_mod, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(main_mod, "converse", broken)
    monkeypatch.setattr(main_mod.voice_service, "synthesize_result",
                        lambda t: TTSResult(audio=wav_bytes(), mime="audio/wav", provider="voicebox"))
    res = client.post("/finzo/voice/chat", headers=account["headers"],
                      data={"transcript": "how much did i spend"})
    body = res.json()
    assert res.status_code == 200 and body["ok"] is False
    assert body["error"]["code"] == "LLM_FAILED"
    assert "database is locked" not in json.dumps(body)  # internals stay in the log


def test_speak_false_skips_tts(client, account, fake_llm, main_mod, monkeypatch):
    def must_not_run(text):
        raise AssertionError("TTS called with speak=false")

    monkeypatch.setattr(main_mod.voice_service, "synthesize_result", must_not_run)
    body = client.post("/finzo/voice/chat", headers=account["headers"],
                       data={"transcript": "how much did i spend on food", "speak": "false"}).json()
    assert body["ok"] and body["audio_b64"] is None


def test_requires_login(client):
    assert client.post("/finzo/voice/chat", data={"transcript": "hi"}).status_code == 401
    assert client.get("/finzo/voice/health").status_code == 401
    assert client.get("/voice/handsfree/status").status_code == 401


# --------------------------------------------------------------------------- #
# health + hands-free status
# --------------------------------------------------------------------------- #
def test_health_reports_voicebox_down(client, account, main_mod, monkeypatch):
    monkeypatch.setattr(main_mod.voice_service, "voicebox_health", lambda fresh=True: {
        "ok": False, "error": "Cannot reach Voicebox", "code": "VOICEBOX_UNAVAILABLE",
        "config": {"enabled": True, "voice_id_configured": False, "local": True}})
    body = client.get("/finzo/voice/health", headers=account["headers"]).json()
    assert body["voicebox"]["ok"] is False
    assert isinstance(body["stt_providers"], list) and isinstance(body["tts_providers"], list)
    assert body["handsfree"]["running"] is False


def test_handsfree_status_hides_transcripts_from_other_accounts(client, account):
    from voice.handsfree.state import StatusFile, VoiceState

    StatusFile(static={"user_id": account["user_id"]}).publish(
        VoiceState.SPEAKING, {"last_transcript": "how much on food", "last_response": "4,850 rupees"})

    mine = client.get("/voice/handsfree/status", headers=account["headers"]).json()
    assert mine["running"] and mine["state"] == "SPEAKING"
    assert mine["last_response"] == "4,850 rupees"

    other = _register(client)
    theirs = client.get("/voice/handsfree/status", headers=other["headers"]).json()
    assert theirs["state"] == "SPEAKING" and "last_response" not in theirs
    assert client.post("/voice/handsfree/stop", headers=other["headers"]).status_code == 403


def test_handsfree_stop_writes_the_request(client, account):
    from voice.handsfree.state import StatusFile, VoiceState, stop_request_path

    StatusFile(static={"user_id": account["user_id"]}).publish(VoiceState.LISTENING_FOR_WAKE_WORD)
    res = client.post("/voice/handsfree/stop", headers=account["headers"])
    assert res.json() == {"stopping": True}
    assert stop_request_path().exists()


def test_stale_status_reads_as_stopped(client, account):
    from voice.handsfree.state import StatusFile, VoiceState, status_path

    StatusFile(static={"user_id": account["user_id"]}).publish(VoiceState.THINKING)
    doc = json.loads(status_path().read_text())
    doc["updated_at"] -= 60  # daemon crashed a minute ago
    status_path().write_text(json.dumps(doc))
    body = client.get("/voice/handsfree/status", headers=account["headers"]).json()
    assert body["running"] is False and body["state"] == "IDLE"
