"""Voicebox settings, read once from the environment.

Voicebox (https://github.com/jamiepine/voicebox) is a local voice studio with a
FastAPI server, by default on 127.0.0.1:17493. Nothing outside ``voice/voicebox``
should read these variables; the rest of the app talks to the STT/TTS registries.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _str(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# Language codes Voicebox's GenerationRequest accepts (backend/models.py).
TTS_LANGUAGES = frozenset(
    "zh en ja ko de fr ru pt es it he ar da el fi hi ms nl no pl sv sw tr".split()
)
# TranscriptionRequest is narrower than generation.
STT_LANGUAGES = frozenset("en zh ja ko de fr ru pt es it".split())
STT_MODELS = frozenset({"base", "small", "medium", "large", "turbo"})
ENGINES = frozenset(
    {"qwen", "qwen_custom_voice", "luxtts", "chatterbox", "chatterbox_turbo", "tada", "kokoro"}
)


@dataclass(frozen=True)
class VoiceboxConfig:
    enabled: bool = field(default_factory=lambda: _flag("VOICEBOX_ENABLED", True))
    base_url: str = field(
        default_factory=lambda: _str("VOICEBOX_BASE_URL", "http://127.0.0.1:17493").rstrip("/")
    )
    #: Informational only. Finzo integrates over REST: MCP exists so an *agent*
    #: can call voicebox.speak, and Finzo is not an MCP client.
    mcp_url: str = field(default_factory=lambda: _str("VOICEBOX_MCP_URL"))
    #: Voice profile id OR profile name. Required for speech output.
    voice_id: str = field(default_factory=lambda: _str("VOICEBOX_VOICE_ID"))
    #: Optional engine override; empty uses the profile's default engine.
    engine: str = field(default_factory=lambda: _str("VOICEBOX_ENGINE").lower())
    language: str = field(default_factory=lambda: _str("VOICEBOX_LANGUAGE", "en").lower())
    #: Whisper size Voicebox should use for /transcribe; empty uses its default.
    stt_model: str = field(default_factory=lambda: _str("VOICEBOX_STT_MODEL").lower())
    #: Natural-language delivery hint. Only Qwen engines honour it.
    instruct: str = field(default_factory=lambda: _str("VOICEBOX_INSTRUCT"))
    timeout_seconds: float = field(default_factory=lambda: _float("VOICEBOX_TIMEOUT", 60.0))
    health_ttl_seconds: float = field(
        default_factory=lambda: _float("VOICEBOX_HEALTH_TTL", 15.0)
    )

    @property
    def is_loopback(self) -> bool:
        """True when Voicebox runs on this machine.

        Answer text contains the user's real balances, so a remote Voicebox means
        that financial data leaves the machine. Callers log a warning for it.
        """
        host = (urlparse(self.base_url).hostname or "").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def tts_language(self) -> str:
        return self.language if self.language in TTS_LANGUAGES else "en"

    def stt_language(self) -> str | None:
        return self.language if self.language in STT_LANGUAGES else None

    def snapshot(self) -> dict:
        """Safe to expose: no secrets exist here, but keep it explicit anyway."""
        return {
            "enabled": self.enabled,
            "base_url": self.base_url,
            "mcp_url": self.mcp_url or None,
            "voice_id_configured": bool(self.voice_id),
            "engine": self.engine or None,
            "language": self.language,
            "stt_model": self.stt_model or None,
            "local": self.is_loopback,
        }


def load_config() -> VoiceboxConfig:
    return VoiceboxConfig()
