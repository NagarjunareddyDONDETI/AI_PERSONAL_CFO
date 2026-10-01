"""Hands-free daemon settings. Every value comes from the environment.

Whisper model, device and precision are NOT redefined here: they come from the
shared ``voice.config.VoiceConfig`` (WHISPER_MODEL / WHISPER_DEVICE /
WHISPER_COMPUTE_TYPE), so the daemon and the API server always agree.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _int(name: str, default: int, lo: int, hi: int) -> int:
    return int(_float(name, default, lo, hi))


def _csv(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw or not raw.strip():
        return list(default)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


@dataclass(frozen=True)
class HandsFreeConfig:
    voice_enabled: bool = field(default_factory=lambda: _flag("VOICE_ENABLED", True))
    wake_word_enabled: bool = field(default_factory=lambda: _flag("WAKE_WORD_ENABLED", True))
    #: Configured phrase. Its name token ("finzo") also activates on its own.
    wake_word: str = field(default_factory=lambda: _str("WAKE_WORD", "hey finzo"))
    #: Small model used only to spot the wake phrase. Kept separate from
    #: WHISPER_MODEL so idle listening stays cheap: tiny.en decodes a short clip in
    #: well under half a second on a laptop CPU.
    wake_model: str = field(default_factory=lambda: _str("WAKE_WHISPER_MODEL", "tiny.en"))
    #: Only the start of an utterance is decoded to look for the wake phrase.
    wake_probe_seconds: float = field(
        default_factory=lambda: _float("WAKE_PROBE_SECONDS", 2.5, 1.0, 6.0)
    )

    sample_rate: int = field(default_factory=lambda: _int("AUDIO_SAMPLE_RATE", 16000, 8000, 48000))
    max_record_seconds: float = field(
        default_factory=lambda: _float("MAX_RECORD_SECONDS", 20.0, 3.0, 120.0)
    )
    silence_timeout: float = field(
        default_factory=lambda: _float("SILENCE_TIMEOUT", 1.2, 0.3, 5.0)
    )
    vad_aggressiveness: int = field(default_factory=lambda: _int("VAD_AGGRESSIVENESS", 2, 0, 3))
    #: Seconds to wait for a question after "Yes?" before going back to sleep.
    listen_timeout: float = field(default_factory=lambda: _float("LISTEN_TIMEOUT", 8.0, 2.0, 60.0))
    #: After an answer, a follow-up needs no wake word for this long. 0 disables.
    followup_seconds: float = field(
        default_factory=lambda: _float("FOLLOWUP_SECONDS", 6.0, 0.0, 60.0)
    )
    #: sounddevice input device index or name substring; empty = system default.
    mic_device: str = field(default_factory=lambda: _str("MIC_DEVICE"))

    #: Local-only by default: answer text holds real balances, so a closed
    #: Voicebox falls back to Windows SAPI rather than to a cloud TTS.
    tts_chain: list[str] = field(
        default_factory=lambda: _csv("FINZO_DAEMON_TTS", ["voicebox", "pyttsx3"])
    )
    stt_chain: list[str] = field(
        default_factory=lambda: _csv("FINZO_DAEMON_STT", ["faster_whisper", "voicebox"])
    )
    #: Substring of a Windows SAPI voice name. "David" is the stock male en-US voice.
    sapi_voice: str = field(default_factory=lambda: _str("PYTTSX3_VOICE", "David"))
    sapi_rate: int = field(default_factory=lambda: _int("PYTTSX3_RATE", 172, 80, 320))

    #: Whose financial data the daemon answers about.
    user_email: str = field(default_factory=lambda: _str("FINZO_VOICE_USER_EMAIL"))
    debug: bool = field(default_factory=lambda: _flag("VOICE_DEBUG", False))

    @property
    def frame_ms(self) -> int:
        return 30  # one of the three frame sizes webrtcvad accepts

    @property
    def frame_samples(self) -> int:
        return self.sample_rate * self.frame_ms // 1000

    def snapshot(self) -> dict:
        return {
            "wake_word": self.wake_word if self.wake_word_enabled else None,
            "wake_model": self.wake_model,
            "sample_rate": self.sample_rate,
            "silence_timeout": self.silence_timeout,
            "max_record_seconds": self.max_record_seconds,
            "followup_seconds": self.followup_seconds,
            "tts_chain": self.tts_chain,
            "stt_chain": self.stt_chain,
        }


def load_config() -> HandsFreeConfig:
    return HandsFreeConfig()
