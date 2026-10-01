"""Voicebox TTS provider: speech in a voice profile from the local Voicebox app."""
from __future__ import annotations

import logging
import time

from ..voicebox import VoiceboxClient, VoiceboxError, get_client
from .base import TTSProvider, TTSResult

logger = logging.getLogger("voice.tts.voicebox")


class VoiceboxTTSProvider(TTSProvider):
    name = "voicebox"
    offline = True

    def __init__(self, client: VoiceboxClient | None = None) -> None:
        self._client = client

    @property
    def client(self) -> VoiceboxClient:
        return self._client or get_client()

    def is_available(self) -> bool:
        # Without a profile every call would fail, so do not advertise it.
        return bool(self.client.config.voice_id) and self.client.is_up()

    def synthesize(self, text: str, *, lang: str = "en", voice: str | None = None) -> TTSResult:
        # `lang` and `voice` are ignored on purpose: the voice profile fixes both,
        # and a per-call override would silently switch Finzo's voice.
        started = time.perf_counter()
        try:
            audio = self.client.synthesize(text)
        except VoiceboxError as exc:
            logger.info("voicebox tts failed code=%s", exc.code)
            return TTSResult(provider=self.name, error=f"{exc.code}: {exc}")
        latency = (time.perf_counter() - started) * 1000
        logger.info("voicebox tts ok bytes=%d %.0fms", len(audio), latency)
        return TTSResult(
            audio=audio, mime="audio/wav", provider=self.name, latency_ms=round(latency, 1)
        )
