"""Speech output for the hands-free daemon: ``speak(text)``, ``stop()``, ``is_speaking()``.

Every engine renders to WAV and one player plays it. That is what makes barge-in
reliable: stopping is always ``sounddevice.stop()``, whatever produced the audio.
Asking pyttsx3 to stop mid-sentence from another thread is not dependable on
SAPI, whereas stopping a playing buffer always is.

Engines, tried in FINZO_DAEMON_TTS order (default voicebox, pyttsx3):
  voicebox  the voice profile from the local Voicebox app
  pyttsx3   Windows SAPI, fully offline, male "Microsoft David" by default
Neither sends the answer text off the machine.
"""
from __future__ import annotations

import abc
import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from .audio import decode_wav

logger = logging.getLogger("voice.handsfree.speaker")


class Synth(abc.ABC):
    name = "base"

    def available(self) -> bool:
        return True

    @abc.abstractmethod
    def render(self, text: str) -> bytes:
        """Return WAV bytes. May raise; the speaker falls through to the next."""


class VoiceboxSynth(Synth):
    name = "voicebox"

    def __init__(self) -> None:
        from ..voicebox import get_client

        self._client = get_client()

    def available(self) -> bool:
        if not self._client.config.voice_id:
            return False
        # Blocking probe is fine here: it runs on the daemon, off any request path.
        return bool(self._client.health().get("ok"))

    def render(self, text: str) -> bytes:
        return self._client.synthesize(text)


class SapiSynth(Synth):
    """pyttsx3 over Windows SAPI5, rendered to a temporary WAV.

    COM objects are apartment-bound, so the engine is created lazily on the
    thread that first speaks and every later call must come from that thread. The
    assistant loop is single-threaded, which satisfies this.
    """

    name = "pyttsx3"

    def __init__(self, *, voice_hint: str = "David", rate: int = 172) -> None:
        self._voice_hint = voice_hint.lower()
        self._rate = rate
        self._engine = None
        self._owner: int | None = None
        self.voice_name: str | None = None

    def available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return True

    def _get_engine(self):
        if self._engine is not None:
            if self._owner != threading.get_ident():
                raise RuntimeError("SAPI engine used from a different thread")
            return self._engine
        import pyttsx3

        engine = pyttsx3.init()
        voices = engine.getProperty("voices") or []
        chosen = next(
            (v for v in voices if self._voice_hint and self._voice_hint in (v.name or "").lower()),
            None,
        )
        if chosen is None:
            # Prefer any male-flagged voice before the engine default.
            chosen = next((v for v in voices if "male" in str(getattr(v, "gender", "")).lower()), None)
        if chosen is not None:
            engine.setProperty("voice", chosen.id)
            self.voice_name = chosen.name
        engine.setProperty("rate", self._rate)  # ~170 wpm: calm, not slow
        self._engine = engine
        self._owner = threading.get_ident()
        logger.info("SAPI voice: %s rate=%d", self.voice_name or "default", self._rate)
        return engine

    def render(self, text: str) -> bytes:
        engine = self._get_engine()
        fd, path = tempfile.mkstemp(suffix=".wav", prefix="finzo_tts_")
        os.close(fd)
        try:
            engine.save_to_file(text, path)
            engine.runAndWait()
            data = Path(path).read_bytes()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if len(data) < 44:
            raise RuntimeError("SAPI produced no audio")
        return data


class Speaker(abc.ABC):
    @abc.abstractmethod
    def speak(self, text: str) -> bool:
        """Start speaking. Non-blocking. False when nothing could be played."""

    @abc.abstractmethod
    def stop(self) -> None: ...

    @abc.abstractmethod
    def is_speaking(self) -> bool: ...

    def wait(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while self.is_speaking() and time.monotonic() < deadline:
            time.sleep(0.03)

    @property
    def engine_name(self) -> str:
        return "none"


class NullSpeaker(Speaker):
    """TTS disabled or unavailable: answers are logged and published, not spoken."""

    def speak(self, text: str) -> bool:
        logger.info("speech output disabled; answer not spoken (%d chars)", len(text))
        return False

    def stop(self) -> None:
        pass

    def is_speaking(self) -> bool:
        return False


class PlaybackSpeaker(Speaker):
    def __init__(
        self,
        synths: list[Synth],
        *,
        playback: bool = True,
        save_dir: str | None = None,
    ) -> None:
        self._synths = synths
        self._playback = playback
        self._save_dir = Path(save_dir) if save_dir else None
        if self._save_dir:
            self._save_dir.mkdir(parents=True, exist_ok=True)
        self._ends_at = 0.0
        self._counter = 0
        self.last_engine = "none"
        self.last_audio_seconds = 0.0
        #: Engines skipped or failed on the last speak(), with the reason.
        self.last_failures: list[tuple[str, str]] = []

    @property
    def engine_name(self) -> str:
        return ",".join(s.name for s in self._synths) or "none"

    def _render(self, text: str) -> tuple[bytes, str] | None:
        self.last_failures = []
        for synth in self._synths:
            try:
                if not synth.available():
                    self.last_failures.append((synth.name, "not available"))
                    continue
                return synth.render(text), synth.name
            except Exception as exc:  # noqa: BLE001
                self.last_failures.append((synth.name, str(exc)[:160]))
                logger.warning("TTS %s failed (%s); trying next engine", synth.name, str(exc)[:160])
        return None

    def speak(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        self.stop()  # never two responses at once
        rendered = self._render(text)
        if rendered is None:
            logger.warning("no TTS engine could speak; answer shown in status only")
            return False
        wav, engine = rendered
        self.last_engine = engine
        try:
            samples, rate = decode_wav(wav)
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not decode %s audio: %s", engine, exc)
            return False
        self.last_audio_seconds = samples.size / rate
        if self._save_dir:
            # Diagnostic copy only: a disk problem here must never cost the user
            # their answer, so failures are logged and playback continues.
            self._counter += 1
            try:
                self._save_dir.mkdir(parents=True, exist_ok=True)
                (self._save_dir / f"finzo_{int(time.time())}_{self._counter:02d}.wav").write_bytes(wav)
            except OSError as exc:
                logger.warning("could not save speech copy: %s", exc)
        if not self._playback:
            return True
        try:
            import sounddevice as sd

            sd.play(samples, rate)
        except Exception as exc:  # noqa: BLE001
            logger.warning("audio output failed: %s", exc)
            return False
        self._ends_at = time.monotonic() + self.last_audio_seconds + 0.15
        logger.info("speaking via %s (%.1fs)", engine, self.last_audio_seconds)
        return True

    def stop(self) -> None:
        if self._ends_at and self._playback:
            try:
                import sounddevice as sd

                sd.stop()
            except Exception:  # noqa: BLE001
                pass
        self._ends_at = 0.0

    def is_speaking(self) -> bool:
        return time.monotonic() < self._ends_at


def build_speaker(chain: list[str], *, voice_hint: str, rate: int, playback: bool = True,
                  save_dir: str | None = None) -> Speaker:
    synths: list[Synth] = []
    for name in chain:
        try:
            if name == "voicebox":
                synths.append(VoiceboxSynth())
            elif name in ("pyttsx3", "sapi", "local"):
                synths.append(SapiSynth(voice_hint=voice_hint, rate=rate))
            elif name in ("none", "off"):
                return NullSpeaker()
            else:
                logger.warning("unknown FINZO_DAEMON_TTS entry %r ignored", name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TTS engine %s unavailable: %s", name, exc)
    if not synths:
        return NullSpeaker()
    return PlaybackSpeaker(synths, playback=playback, save_dir=save_dir)
