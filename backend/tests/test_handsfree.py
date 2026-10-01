"""Hands-free daemon: VAD segmentation, state machine, wake handling, the turn
loop (with fakes), CUDA->CPU fallback, and one real-audio run.

The real-audio test synthesizes "Hey Finzo, how much did I spend on food this
month?" with Windows SAPI and pushes it through the actual VAD, the actual tiny
Whisper wake detector and the actual accurate Whisper model. It is skipped where
those are not installed or not downloaded.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from voice.handsfree import state as st
from voice.handsfree.assistant import MSG_NOT_UNDERSTOOD, MSG_STT_DOWN, HandsFreeAssistant
from voice.handsfree.audio import Segmenter, Utterance, _EnergyVad, float_to_wav_bytes, decode_wav
from voice.handsfree.config import HandsFreeConfig
from voice.handsfree.speaker import NullSpeaker, Speaker
from voice.handsfree.wake_detector import WakeDetector, strip_leading_wake
from voice import wake as wake_text

RATE = 16000
FRAME = RATE * 30 // 1000


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FINZO_VOICE_STATE_DIR", str(tmp_path))


def frames(signal: np.ndarray) -> list[bytes]:
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16).tobytes()
    step = FRAME * 2
    return [pcm[i : i + step] for i in range(0, len(pcm) - step + 1, step)]


def tone(seconds: float, amp: float = 0.4) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * RATE), np.float32)


class LoudVad:
    """Deterministic VAD for tests: a frame is speech when it is loud."""

    def is_speech(self, frame: bytes) -> bool:
        return np.abs(np.frombuffer(frame, np.int16)).max() > 3000


# --------------------------------------------------------------------------- #
# VAD / segmentation
# --------------------------------------------------------------------------- #
def feed_all(seg: Segmenter, signal: np.ndarray) -> list[Utterance]:
    out = []
    for f in frames(signal):
        utt = seg.feed(f)
        if utt is not None:
            out.append(utt)
    return out


def test_segmenter_cuts_on_trailing_silence():
    seg = Segmenter(sample_rate=RATE, silence_timeout=1.2, vad=LoudVad())
    utts = feed_all(seg, np.concatenate([silence(0.5), tone(1.0), silence(1.5)]))
    assert len(utts) == 1
    # speech + pre-roll + the silence window that ended it
    assert 1.0 < utts[0].seconds < 2.8
    assert not utts[0].truncated


def test_segmenter_waits_through_a_short_pause():
    seg = Segmenter(sample_rate=RATE, silence_timeout=1.2, vad=LoudVad())
    utts = feed_all(seg, np.concatenate([tone(0.8), silence(0.6), tone(0.8), silence(1.5)]))
    assert len(utts) == 1  # "how much did I spend ... on food" stays one question


def test_segmenter_ignores_a_click():
    seg = Segmenter(sample_rate=RATE, vad=LoudVad())
    assert feed_all(seg, np.concatenate([silence(0.3), tone(0.09), silence(2.0)])) == []


def test_segmenter_enforces_max_duration():
    seg = Segmenter(sample_rate=RATE, max_seconds=3.0, vad=LoudVad())
    utts = feed_all(seg, tone(5.0))
    assert utts and utts[0].truncated and utts[0].seconds <= 3.05


def test_energy_vad_fallback():
    vad = _EnergyVad()
    quiet = frames(silence(0.3) + 0.001)
    loud = frames(tone(0.3))
    assert not any(vad.is_speech(f) for f in quiet)
    assert all(vad.is_speech(f) for f in loud)


def test_wav_round_trip():
    samples, rate = decode_wav(float_to_wav_bytes(tone(0.5), RATE))
    assert rate == RATE and abs(samples.size - RATE // 2) <= 1


# --------------------------------------------------------------------------- #
# state machine + status file
# --------------------------------------------------------------------------- #
def test_state_machine_rejects_illegal_jumps():
    sm = st.StateMachine()
    assert sm.to(st.VoiceState.LISTENING_FOR_WAKE_WORD)
    assert not sm.to(st.VoiceState.SPEAKING)  # cannot speak before being asked
    assert sm.state == st.VoiceState.LISTENING_FOR_WAKE_WORD


def test_error_and_idle_are_reachable_from_anywhere():
    sm = st.StateMachine()
    for s in (st.VoiceState.LISTENING_FOR_WAKE_WORD, st.VoiceState.WAKE_DETECTED,
              st.VoiceState.TRANSCRIBING, st.VoiceState.THINKING):
        assert sm.to(s)
    assert sm.to(st.VoiceState.ERROR)
    assert sm.to(st.VoiceState.SPEAKING)  # the apology must be speakable
    assert sm.to(st.VoiceState.IDLE)


def test_status_file_publishes_state():
    status = st.StatusFile(static={"user_id": "u1"})
    st.StateMachine(publisher=status).to(st.VoiceState.LISTENING_FOR_WAKE_WORD)
    doc = st.read_status()
    assert doc["running"] and doc["state"] == "LISTENING_FOR_WAKE_WORD" and doc["user_id"] == "u1"
    status.clear()
    assert st.read_status()["running"] is False


# --------------------------------------------------------------------------- #
# wake phrase
# --------------------------------------------------------------------------- #
def test_configured_phrase_and_bare_name_both_activate():
    name = wake_text.wake_name("hey finzo")
    assert name == "finzo"
    assert wake_text.match_wake_word("Hey Finzo, how much?", wake_word=name).query == "how much"
    assert wake_text.match_wake_word("Finzo", wake_word=name)
    assert not wake_text.match_wake_word("my financial summary", wake_word=name)


def test_renamed_assistant():
    assert wake_text.match_wake_word("ok penny what did i spend", wake_word="penny").query == "what did i spend"


def test_strip_wake_from_accurate_transcript_with_different_spelling():
    assert strip_leading_wake("Hey Fenzo, how much did I spend on food?", "finzo") == \
        "how much did i spend on food"
    # Two edits away: beyond the exact matcher, caught by the looser strip.
    assert strip_leading_wake("Hey Fenso, what about last month?", "finzo") == "what about last month"
    # Three edits away is left alone on purpose; a wider net eats real words.
    assert strip_leading_wake("Hey Vinsu, what about last month?", "finzo").startswith("hey vinsu")
    assert strip_leading_wake("what about last month", "finzo") == "what about last month"


# --------------------------------------------------------------------------- #
# the loop, with fakes
# --------------------------------------------------------------------------- #
class ScriptedWake(WakeDetector):
    name = "finzo"

    def __init__(self):
        self.heard: list[str] = []

    def probe(self, utterance):
        return self.heard.pop(0) if self.heard else ""


class ScriptedTranscriber:
    def __init__(self):
        self.texts: list[object] = []
        self.last_provider = "fake"

    def transcribe(self, utt):
        item = self.texts.pop(0) if self.texts else ""
        if isinstance(item, Exception):
            raise item
        return item


class FakeSpeaker(Speaker):
    def __init__(self):
        self.said: list[str] = []
        self.speaking = False
        self.stops = 0

    def speak(self, text):
        self.said.append(text)
        self.speaking = True
        return True

    def stop(self):
        self.stops += 1
        self.speaking = False

    def is_speaking(self):
        return self.speaking

    def wait(self, timeout=30.0):
        self.speaking = False


class FakeBridge:
    def __init__(self, reply=None):
        self.asked: list[str] = []
        self.reply = reply or {"ok": True, "action": "answer",
                               "speech": "You spent 4,850 rupees on food this month.",
                               "response": "You spent ₹4,850 on food this month.",
                               "intent": "spending", "llm_used": True}

    def ask(self, text):
        self.asked.append(text)
        return self.reply


class NullSource:
    live = True
    exhausted = False

    def start(self): ...
    def close(self): ...
    def flush(self): ...
    def read(self, timeout=0.1): return None


def make(speaker=None, bridge=None, **cfg):
    config = HandsFreeConfig(**{"followup_seconds": 6.0, "listen_timeout": 8.0, **cfg})
    wake, tx = ScriptedWake(), ScriptedTranscriber()
    a = HandsFreeAssistant(cfg=config, source=NullSource(), wake=wake, transcriber=tx,
                           speaker=speaker or FakeSpeaker(), bridge=bridge or FakeBridge(),
                           status=st.StatusFile())
    a.sm.to(st.VoiceState.LISTENING_FOR_WAKE_WORD)
    return a, wake, tx


def utt(seconds: float = 3.5) -> Utterance:
    return Utterance(tone(seconds), RATE)


def test_question_in_the_same_breath_as_the_wake_word():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo, how much did I spend on"]
    tx.texts = ["Hey Finzo, how much did I spend on food this month?"]
    a._on_utterance(utt(3.5))
    assert a.bridge.asked == ["how much did i spend on food this month"]
    assert a.speaker.said == ["You spent 4,850 rupees on food this month."]
    assert a.sm.state == st.VoiceState.SPEAKING
    a.speaker.speaking = False
    a._tick(0)
    assert a.sm.state == st.VoiceState.LISTENING  # follow-up window, no wake word


def test_conversation_context_is_refreshed_when_speech_ends():
    """A 20 s spoken answer used to eat the 30 s context window, so the
    follow-up arrived after the topic had been forgotten (observed)."""

    class TrackingBridge(FakeBridge):
        kept = 0

        def keep_alive(self):
            TrackingBridge.kept += 1

    a, wake, tx = make(bridge=TrackingBridge())
    wake.heard = ["Hey Finzo, how much did I spend on food"]
    tx.texts = ["Hey Finzo, how much did I spend on food?"]
    a._on_utterance(utt(3.5))
    assert TrackingBridge.kept == 0  # still speaking
    a.speaker.speaking = False
    a._tick(0)
    assert TrackingBridge.kept == 1 and a.sm.state == st.VoiceState.LISTENING


def test_saving_a_speech_copy_can_fail_without_losing_the_answer(tmp_path):
    from voice.handsfree.speaker import PlaybackSpeaker, Synth

    class Wav(Synth):
        name = "fake"

        def render(self, text):
            return float_to_wav_bytes(tone(0.2), RATE)

    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file in the way")
    speaker = PlaybackSpeaker([Wav()], playback=False, save_dir=None)
    speaker._save_dir = blocker / "answers"  # mkdir under a file fails
    assert speaker.speak("hello") is True


def test_bare_wake_word_acknowledges_then_takes_the_question():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo."]
    a._on_utterance(utt(0.8))
    assert a.speaker.said == ["Yes?"] and a.sm.state == st.VoiceState.LISTENING
    wake.heard = ["what about last month"]
    tx.texts = ["What about last month?"]
    a._on_utterance(utt(1.5))
    assert a.bridge.asked == ["What about last month?"]


def test_ordinary_speech_does_not_wake_finzo():
    a, wake, _ = make()
    wake.heard = ["I need to check my financial summary later"]
    a._on_utterance(utt(2.0))
    assert a.bridge.asked == [] and a.speaker.said == []
    assert a.sm.state == st.VoiceState.LISTENING_FOR_WAKE_WORD


def test_wake_word_interrupts_and_starts_a_new_turn():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo, how much did I spend"]
    tx.texts = ["Hey Finzo, how much did I spend on food?"]
    a._on_utterance(utt(3.5))
    assert a.sm.state == st.VoiceState.SPEAKING
    wake.heard = ["Hey Finzo, what about last month"]
    tx.texts = ["Hey Finzo, what about last month?"]
    a._on_utterance(utt(3.0))
    assert a.speaker.stops >= 1
    assert a.bridge.asked[-1] == "what about last month"
    assert len(a.speaker.said) == 2  # never two answers at once: the first was stopped


def test_stop_phrase_interrupts():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo, summarize my finances"]
    tx.texts = ["Hey Finzo, summarize my finances."]
    a._on_utterance(utt(3.5))
    wake.heard = ["stop"]
    a._on_utterance(utt(0.6))
    assert a.speaker.stops >= 1 and a.sm.state == st.VoiceState.LISTENING
    assert len(a.bridge.asked) == 1


def test_finzo_hearing_itself_is_ignored():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo, how much on food"]
    tx.texts = ["Hey Finzo, how much on food?"]
    a._on_utterance(utt(3.5))
    wake.heard = ["You spent 4,850 rupees on food this month."]
    a._on_utterance(utt(2.5))
    assert a.speaker.stops == 0 and a.speaker.speaking  # no barge-in on its own voice
    assert len(a.bridge.asked) == 1


def test_tts_disabled_does_not_block_the_loop():
    a, wake, tx = make(speaker=NullSpeaker())
    wake.heard = ["Hey Finzo, how much did I spend"]
    tx.texts = ["Hey Finzo, how much did I spend?"]
    a._on_utterance(utt(3.5))
    assert a.bridge.asked and a.sm.state == st.VoiceState.LISTENING
    assert a.turns[-1]["answer"]  # still published for the dashboard


def test_unintelligible_speech():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo."]
    a._on_utterance(utt(0.8))
    wake.heard = ["mm"]
    tx.texts = [""]
    a._on_utterance(utt(1.0))
    assert a.speaker.said[-1] == MSG_NOT_UNDERSTOOD and a.bridge.asked == []


def test_speech_recognition_down():
    a, wake, tx = make()
    wake.heard = ["Hey Finzo, how much"]
    tx.texts = [RuntimeError("no STT engine available")]
    a._on_utterance(utt(3.5))
    assert a.speaker.said[-1] == MSG_STT_DOWN


def test_financial_pipeline_failure_is_spoken_not_raised():
    bridge = FakeBridge(reply={"ok": False, "action": "answer", "response": "",
                               "speech": "I'm having trouble reaching your financial data right now."})
    a, wake, tx = make(bridge=bridge)
    wake.heard = ["Hey Finzo, how much"]
    tx.texts = ["Hey Finzo, how much did I spend?"]
    a._on_utterance(utt(3.5))
    assert "trouble" in a.speaker.said[-1]


def test_unexpected_exception_recovers():
    class Exploding(FakeBridge):
        def ask(self, text):
            raise ValueError("boom")

    a, wake, tx = make(bridge=Exploding())
    wake.heard = ["Hey Finzo, how much"]
    tx.texts = ["Hey Finzo, how much?"]
    a._on_utterance(utt(3.5))
    assert a.sm.state == st.VoiceState.SPEAKING  # apologising, not stuck in ERROR
    a.speaker.speaking = False
    a._tick(0)
    assert a.sm.state == st.VoiceState.LISTENING


def test_listen_window_times_out_back_to_wake_word():
    a, wake, _ = make(listen_timeout=2.0)
    wake.heard = ["Hey Finzo."]
    a._on_utterance(utt(0.8))
    assert a.sm.state == st.VoiceState.LISTENING
    a._tick(a._deadline + 0.1)
    assert a.sm.state == st.VoiceState.LISTENING_FOR_WAKE_WORD


# --------------------------------------------------------------------------- #
# CUDA -> CPU fallback
# --------------------------------------------------------------------------- #
@pytest.fixture
def fw(monkeypatch):
    from voice.stt import faster_whisper_local as fw_mod

    monkeypatch.setattr(fw_mod, "_models", {})
    monkeypatch.setattr(fw_mod, "_cuda_broken", None)
    return fw_mod


def test_missing_cuda_libraries_fall_back_to_cpu(fw, monkeypatch):
    attempts = []

    def fake_load(size, device, compute):
        attempts.append(device)
        if device == "cuda":
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return object()

    monkeypatch.setattr(fw, "cuda_device_count", lambda: 1)
    monkeypatch.setattr(fw, "_try_load", fake_load)
    assert fw.load_model("small", "auto", "int8").device == "cpu"
    # CUDA is never retried in the same process: a second attempt was observed
    # to hang instead of failing.
    fw.load_model("tiny.en", "auto", "int8")
    assert attempts == ["cuda", "cpu", "cpu"]
    assert "cublas" in fw.cuda_status()


def test_no_gpu_goes_straight_to_cpu(fw, monkeypatch):
    seen = []
    monkeypatch.setattr(fw, "cuda_device_count", lambda: 0)
    monkeypatch.setattr(fw, "_try_load", lambda s, d, c: seen.append((d, c)) or object())
    assert fw.load_model("small", "auto", "float16").device == "cpu"
    assert seen == [("cpu", "int8")]  # float16 is GPU-only


def test_gpu_out_of_memory_mid_transcription_retries_on_cpu(fw, monkeypatch):
    class Seg:
        text, avg_logprob = " how much did i spend", -0.2

    class GpuModel:
        def transcribe(self, *a, **k):
            raise RuntimeError("CUDA failed with error out of memory")

    class CpuModel:
        def transcribe(self, *a, **k):
            return iter([Seg()]), type("Info", (), {"language": "en"})()

    import threading

    key = "small|auto|int8"
    fw._models[key] = fw.LoadedModel(GpuModel(), "small", "cuda", "int8", threading.Lock())
    monkeypatch.setattr(fw, "_try_load", lambda s, d, c: CpuModel())
    text, conf, lang, device = fw.transcribe_audio(np.zeros(16000, np.float32), size="small")
    assert text == "how much did i spend" and device == "cpu" and conf > 0.5


def test_provider_reports_failure_instead_of_crashing(fw, monkeypatch):
    from voice.config import load_config
    from voice.stt.faster_whisper_local import FasterWhisperProvider

    monkeypatch.setattr(fw, "_try_load", lambda *a: (_ for _ in ()).throw(RuntimeError("no model")))
    monkeypatch.setattr(fw, "cuda_device_count", lambda: 0)
    provider = FasterWhisperProvider(load_config())
    result = provider.transcribe(b"RIFF....")
    assert not result.ok and "no model" in result.error
    assert provider.is_available() is False  # stops being retried every request


# --------------------------------------------------------------------------- #
# startup messages
# --------------------------------------------------------------------------- #
def test_microphone_errors_are_explained():
    from voice.main import _friendly

    assert "microphone" in _friendly(Exception("Error querying device -1 (PortAudio)")).lower()
    assert "microphone" in _friendly(Exception("Invalid device")).lower()


def test_bridge_must_connect_first():
    from voice.handsfree.bridge import BridgeError, CFOBridge

    with pytest.raises(BridgeError):
        CFOBridge().ask("hello")


# --------------------------------------------------------------------------- #
# real audio: SAPI speech -> VAD -> tiny.en wake -> Whisper small
# --------------------------------------------------------------------------- #
def _model_cached(name: str) -> bool:
    try:
        from huggingface_hub import constants
    except Exception:  # noqa: BLE001
        return False
    return (Path(constants.HF_HUB_CACHE) / f"models--Systran--faster-whisper-{name}").exists()


def _sapi_wav(text: str) -> np.ndarray:
    from voice.handsfree.audio import resample
    from voice.handsfree.speaker import SapiSynth

    samples, rate = decode_wav(SapiSynth(voice_hint="Zira", rate=165).render(text))
    return resample(samples, rate, RATE)


@pytest.mark.skipif(sys.platform != "win32", reason="uses Windows SAPI to synthesize the question")
@pytest.mark.skipif(not (_model_cached("tiny.en") and _model_cached("small")),
                    reason="faster-whisper models not downloaded")
def test_real_audio_wake_word_and_question(tmp_path):
    pytest.importorskip("pyttsx3")
    pytest.importorskip("faster_whisper")
    from voice.config import VoiceConfig
    from voice.handsfree.assistant import Transcriber
    from voice.handsfree.audio import FileSource
    from voice.handsfree.wake_detector import WhisperWakeDetector

    audio = np.concatenate([
        silence(0.8), _sapi_wav("Hey Finzo, how much did I spend on food this month?"),
        silence(2.0), _sapi_wav("Hey Finzo, what about last month?"), silence(1.0),
    ]) * 0.8
    wav = tmp_path / "question.wav"
    wav.write_bytes(float_to_wav_bytes(audio, RATE))

    cfg = HandsFreeConfig(stt_chain=["faster_whisper"], followup_seconds=6.0)
    voice_cfg = VoiceConfig(whisper_model="small", whisper_device="cpu", whisper_compute_type="int8")
    bridge = FakeBridge()
    assistant = HandsFreeAssistant(
        cfg=cfg,
        source=FileSource(str(wav), sample_rate=RATE, frame_samples=FRAME),
        wake=WhisperWakeDetector(phrase="hey finzo", model="tiny.en", device="cpu",
                                 compute_type="int8", probe_seconds=2.5),
        transcriber=Transcriber(cfg, voice_cfg),
        speaker=NullSpeaker(),
        bridge=bridge,
        status=st.StatusFile(),
    )
    assistant.run()

    assert len(bridge.asked) == 2, bridge.asked
    first, second = (q.lower() for q in bridge.asked)
    assert "food" in first and "month" in first and "finzo" not in first
    assert "last month" in second and "finzo" not in second
    assert assistant.sm.state == st.VoiceState.IDLE
