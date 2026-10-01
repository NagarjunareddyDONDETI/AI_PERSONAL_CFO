"""Voicebox client and providers, against a mocked Voicebox server.

Routes and payloads mirror Voicebox's own backend/routes/*.py and models.py:
GET /health, GET /profiles, POST /transcribe (multipart), POST /generate/stream.
"""
from __future__ import annotations

import io
import json
import time
import wave

import httpx
import pytest
import respx

from voice.config import load_config as load_voice_config
from voice.stt.voicebox import VoiceboxSTTProvider
from voice.tts.voicebox import VoiceboxTTSProvider
from voice.voicebox import (
    VoiceboxBadResponse,
    VoiceboxClient,
    VoiceboxConfig,
    VoiceboxNotReady,
    VoiceboxUnavailable,
)

BASE = "http://127.0.0.1:17493"
PROFILES = [
    {"id": "11111111-aaaa", "name": "Finzo", "language": "en"},
    {"id": "22222222-bbbb", "name": "Narrator", "language": "en"},
]


def wav_bytes(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate))
    return buf.getvalue()


def make_client(**overrides) -> VoiceboxClient:
    cfg = dict(enabled=True, base_url=BASE, voice_id="Finzo", engine="", language="en",
               stt_model="", instruct="", timeout_seconds=5.0, health_ttl_seconds=60.0)
    cfg.update(overrides)
    return VoiceboxClient(VoiceboxConfig(**cfg))


# --------------------------------------------------------------------------- #
# connection + health
# --------------------------------------------------------------------------- #
@respx.mock(base_url=BASE)
def test_health_ok(respx_mock):
    respx_mock.get("/health").respond(
        200, json={"status": "healthy", "gpu_available": True, "backend_type": "pytorch"}
    )
    h = make_client().health()
    assert h["ok"] is True
    assert h["backend_type"] == "pytorch"
    assert h["gpu_available"] is True


@respx.mock(base_url=BASE)
def test_health_when_voicebox_not_running(respx_mock):
    respx_mock.get("/health").mock(side_effect=httpx.ConnectError("refused"))
    h = make_client().health()
    assert h["ok"] is False
    assert h["code"] == "VOICEBOX_UNAVAILABLE"
    assert "Is the Voicebox app running?" in h["error"]


@respx.mock(base_url=BASE)
def test_health_malformed_response_is_reported_not_raised(respx_mock):
    respx_mock.get("/health").respond(200, text="<html>not the api</html>")
    h = make_client().health()
    assert h["ok"] is False
    assert h["code"] == "VOICEBOX_BAD_RESPONSE"


@respx.mock(base_url=BASE)
def test_health_unhealthy_status(respx_mock):
    respx_mock.get("/health").respond(200, json={"status": "starting"})
    assert make_client().health()["ok"] is False


@respx.mock(base_url=BASE)
def test_health_is_cached(respx_mock):
    route = respx_mock.get("/health").respond(200, json={"status": "healthy"})
    client = make_client()
    client.health()
    client.health()
    assert route.call_count == 1
    client.health(use_cache=False)
    assert route.call_count == 2


def test_disabled_makes_no_requests():
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.get("/health").respond(200, json={"status": "healthy"})
        client = make_client(enabled=False)
        assert client.health()["ok"] is False
        assert client.is_up() is False
        with pytest.raises(VoiceboxUnavailable):
            client.transcribe(b"audio")
        assert route.call_count == 0


def test_is_up_never_blocks_the_caller():
    """Registries call is_up() on every request; a closed Voicebox must not add
    the Windows refused-connect delay to each one."""
    with respx.mock(base_url=BASE) as mock:
        mock.get("/health").respond(200, json={"status": "healthy"})
        client = make_client()
        started = time.perf_counter()
        first = client.is_up()  # cold cache: answers immediately, refreshes behind
        assert time.perf_counter() - started < 0.2
        assert first is False
        for _ in range(100):
            if client.is_up():
                break
            time.sleep(0.02)
        assert client.is_up() is True


def test_non_loopback_url_is_flagged(caplog):
    caplog.set_level("WARNING", logger="voice.voicebox")
    client = make_client(base_url="http://192.168.1.50:17493")
    assert client.config.is_loopback is False
    assert "financial figures" in caplog.text


# --------------------------------------------------------------------------- #
# profiles
# --------------------------------------------------------------------------- #
@respx.mock(base_url=BASE)
def test_profile_resolves_by_name_case_insensitively(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    assert make_client(voice_id="finzo").resolve_profile_id() == "11111111-aaaa"


@respx.mock(base_url=BASE)
def test_profile_resolves_by_id(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    assert make_client(voice_id="22222222-bbbb").resolve_profile_id() == "22222222-bbbb"


@respx.mock(base_url=BASE)
def test_unknown_profile_lists_the_available_ones(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    with pytest.raises(VoiceboxNotReady) as exc:
        make_client(voice_id="Nobody").resolve_profile_id()
    assert "Finzo" in str(exc.value) and "Narrator" in str(exc.value)


def test_missing_voice_id_explains_the_fix():
    with pytest.raises(VoiceboxNotReady, match="VOICEBOX_VOICE_ID"):
        make_client(voice_id="").resolve_profile_id()


@respx.mock(base_url=BASE)
def test_profiles_malformed(respx_mock):
    respx_mock.get("/profiles").respond(200, json={"items": PROFILES})
    with pytest.raises(VoiceboxBadResponse):
        make_client().list_profiles()


# --------------------------------------------------------------------------- #
# audio -> transcript
# --------------------------------------------------------------------------- #
@respx.mock(base_url=BASE)
def test_transcribe_sends_multipart_and_returns_text(respx_mock):
    route = respx_mock.post("/transcribe").respond(
        200, json={"text": "  How much did I spend on food?  ", "duration": 2.1}
    )
    out = make_client(stt_model="small").transcribe(b"RIFF....WAVE", suffix=".wav")
    assert out == {"text": "How much did I spend on food?", "duration": 2.1}
    body = route.calls.last.request.content
    assert b'name="file"' in body and b'name="language"' in body and b"small" in body


@respx.mock(base_url=BASE)
def test_transcribe_while_whisper_downloads(respx_mock):
    respx_mock.post("/transcribe").respond(
        202, json={"detail": {"message": "downloading", "downloading": True}}
    )
    with pytest.raises(VoiceboxNotReady, match="downloading"):
        make_client().transcribe(b"audio")


@respx.mock(base_url=BASE)
def test_transcribe_malformed_response(respx_mock):
    respx_mock.post("/transcribe").respond(200, json={"transcript": "wrong field"})
    with pytest.raises(VoiceboxBadResponse):
        make_client().transcribe(b"audio")


@respx.mock(base_url=BASE)
def test_transcribe_invalid_audio_is_a_bad_response(respx_mock):
    respx_mock.post("/transcribe").respond(500, json={"detail": "Error opening audio"})
    with pytest.raises(VoiceboxBadResponse, match="500"):
        make_client().transcribe(b"not really audio")


def test_transcribe_rejects_empty_audio_without_calling_voicebox():
    with pytest.raises(VoiceboxBadResponse, match="Empty"):
        make_client().transcribe(b"")


@respx.mock(base_url=BASE)
def test_timeout_is_unavailable(respx_mock):
    respx_mock.post("/transcribe").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(VoiceboxUnavailable, match="timed out"):
        make_client().transcribe(b"audio")


# --------------------------------------------------------------------------- #
# text -> speech
# --------------------------------------------------------------------------- #
@respx.mock(base_url=BASE)
def test_synthesize_returns_wav_and_never_rewrites_text(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    route = respx_mock.post("/generate/stream").respond(
        200, content=wav_bytes(), headers={"content-type": "audio/wav"}
    )
    audio = make_client(engine="kokoro", instruct="calm").synthesize(
        "You spent 4,850 rupees on food."
    )
    assert audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
    sent = json.loads(route.calls.last.request.content)
    assert sent["profile_id"] == "11111111-aaaa"
    assert sent["text"] == "You spent 4,850 rupees on food."
    # A persona rewrite runs Voicebox's own LLM and could reword a figure.
    assert sent["personality"] is False
    assert sent["engine"] == "kokoro" and sent["instruct"] == "calm"


@respx.mock(base_url=BASE)
def test_synthesize_rejects_non_audio(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    respx_mock.post("/generate/stream").respond(200, json={"status": "queued"})
    with pytest.raises(VoiceboxBadResponse, match="did not return WAV"):
        make_client().synthesize("hello")


@respx.mock(base_url=BASE)
def test_voice_model_not_downloaded_explains_the_fix(respx_mock):
    """Exact response observed from Voicebox 0.5.0 on a fresh Kokoro profile."""
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    respx_mock.post("/generate/stream").respond(
        400, json={"detail": "kokoro model is not downloaded yet. Use /generate to trigger a download."}
    )
    with pytest.raises(VoiceboxNotReady, match="generate any short sentence once"):
        make_client().synthesize("hello")


@respx.mock(base_url=BASE)
def test_deleted_profile_is_re_resolved_next_time(respx_mock):
    profiles = respx_mock.get("/profiles").respond(200, json=PROFILES)
    respx_mock.post("/generate/stream").respond(404, json={"detail": "Profile not found"})
    client = make_client()
    with pytest.raises(VoiceboxNotReady):
        client.synthesize("hello")
    with pytest.raises(VoiceboxNotReady):
        client.synthesize("hello")
    assert profiles.call_count == 2  # cache dropped after the 404


def test_synthesize_nothing_to_say():
    with pytest.raises(VoiceboxBadResponse):
        make_client().synthesize("   ")


# --------------------------------------------------------------------------- #
# providers: translate every failure into a result, never an exception
# --------------------------------------------------------------------------- #
@respx.mock(base_url=BASE)
def test_stt_provider_success(respx_mock):
    respx_mock.post("/transcribe").respond(200, json={"text": "what about last month", "duration": 1})
    result = VoiceboxSTTProvider(load_voice_config(), client=make_client()).transcribe(b"x", ".webm")
    assert result.ok and result.text == "what about last month"
    assert result.provider == "voicebox" and result.confidence >= 0.5


@respx.mock(base_url=BASE)
def test_stt_provider_unavailable_does_not_raise(respx_mock):
    respx_mock.post("/transcribe").mock(side_effect=httpx.ConnectError("refused"))
    result = VoiceboxSTTProvider(load_voice_config(), client=make_client()).transcribe(b"x")
    assert not result.ok and result.error.startswith("VOICEBOX_UNAVAILABLE")


@respx.mock(base_url=BASE)
def test_tts_provider_success_is_wav(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    respx_mock.post("/generate/stream").respond(200, content=wav_bytes())
    result = VoiceboxTTSProvider(client=make_client()).synthesize("hello")
    assert result.ok and result.mime == "audio/wav" and result.provider == "voicebox"


@respx.mock(base_url=BASE)
def test_tts_provider_malformed_does_not_raise(respx_mock):
    respx_mock.get("/profiles").respond(200, json=PROFILES)
    respx_mock.post("/generate/stream").respond(200, content=b"garbage")
    result = VoiceboxTTSProvider(client=make_client()).synthesize("hello")
    assert not result.ok and "VOICEBOX_BAD_RESPONSE" in result.error


def test_tts_provider_not_advertised_without_a_voice_profile():
    assert VoiceboxTTSProvider(client=make_client(voice_id="")).is_available() is False


def test_registry_falls_back_when_voicebox_is_down(monkeypatch):
    """Voicebox unavailable -> the next provider in TTS_PROVIDER speaks."""
    from voice.tts.base import TTSResult
    from voice.tts.registry import TTSRegistry

    registry = TTSRegistry(load_voice_config())
    down = VoiceboxTTSProvider(client=make_client(enabled=False))
    registry._providers["voicebox"] = down
    monkeypatch.setattr(
        registry._providers["gtts"], "synthesize",
        lambda text, lang="en", voice=None: TTSResult(audio=b"ID3mp3", provider="gtts"),
    )
    monkeypatch.setattr(registry._providers["gtts"], "is_available", lambda: True)
    result = registry.synthesize("hello")
    assert result.ok and result.provider == "gtts"
    # And the daemon's local-only chain never reaches the cloud provider.
    assert registry.synthesize("hello", only=["voicebox"]).ok is False
