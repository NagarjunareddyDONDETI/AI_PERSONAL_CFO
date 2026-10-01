"""Voicebox STT provider: Whisper running inside the local Voicebox app."""
from __future__ import annotations

import logging
import time

from ..config import VoiceConfig
from ..voicebox import VoiceboxClient, VoiceboxError, get_client
from .base import STTProvider, STTResult

logger = logging.getLogger("voice.stt.voicebox")

# Voicebox's /transcribe returns text and duration only, no log-probs. A fixed
# score just above the registry's retry threshold means a Voicebox transcript is
# accepted rather than automatically re-sent to a cloud provider, which would
# defeat the point of transcribing locally.
_ASSUMED_CONFIDENCE = 0.8


class VoiceboxSTTProvider(STTProvider):
    name = "voicebox"
    offline = True  # runs on this machine; needs no internet once models exist

    def __init__(self, config: VoiceConfig, client: VoiceboxClient | None = None) -> None:
        self._config = config
        self._client = client

    @property
    def client(self) -> VoiceboxClient:
        return self._client or get_client()

    def is_available(self) -> bool:
        return self.client.is_up()

    def transcribe(self, audio_bytes: bytes, suffix: str = ".webm") -> STTResult:
        started = time.perf_counter()
        try:
            out = self.client.transcribe(audio_bytes, suffix=suffix)
        except VoiceboxError as exc:
            logger.info("voicebox stt failed code=%s", exc.code)
            return STTResult(text="", provider=self.name, error=f"{exc.code}: {exc}")
        text = out["text"]
        latency = (time.perf_counter() - started) * 1000
        # Length only: transcripts are user speech about their money.
        logger.info("voicebox stt ok chars=%d %.0fms", len(text), latency)
        return STTResult(
            text=text,
            confidence=_ASSUMED_CONFIDENCE if text else 0.0,
            language=self.client.config.stt_language(),
            provider=self.name,
            latency_ms=round(latency, 1),
        )
