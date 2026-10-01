"""The hands-free loop.

    LISTENING_FOR_WAKE_WORD --"hey finzo ..."--> WAKE_DETECTED
        with a question in the same breath --> TRANSCRIBING --> THINKING --> SPEAKING
        bare wake word --> "Yes?" --> LISTENING --> TRANSCRIBING --> THINKING --> SPEAKING
    SPEAKING --finished--> LISTENING (follow-up window, no wake word) --> LISTENING_FOR_WAKE_WORD
    SPEAKING --wake word or "stop"--> INTERRUPTED --> new turn / listening

Single-threaded on purpose: audio capture runs in sounddevice's callback thread
and only fills a queue, and everything else, including the SAPI engine, which is
bound to the thread that created it, runs here. Audio that arrives while Finzo is
thinking is discarded rather than queued, so it cannot become a stale question.
"""
from __future__ import annotations

import logging
import threading
import time

import numpy as np

from .. import wake as wake_text
from ..config import VoiceConfig
from ..stt.whisper_local import _INITIAL_PROMPT
from .audio import Segmenter, Utterance, float_to_wav_bytes, resample
from .bridge import CFOBridge
from .config import HandsFreeConfig
from .speaker import Speaker
from .state import HEARTBEAT_SECONDS, StateMachine, StatusFile, VoiceState, stop_request_path
from .wake_detector import WakeDetector, strip_leading_wake

logger = logging.getLogger("voice.handsfree")

ACK = "Yes?"
MSG_NOT_UNDERSTOOD = "Sorry, I couldn't understand that. Try again."
MSG_STT_DOWN = "Sorry, speech recognition isn't working right now."

_QUERY_PROMPT = _INITIAL_PROMPT + " The assistant is called Finzo."


class Transcriber:
    """Accurate transcription of a captured question, in FINZO_DAEMON_STT order."""

    def __init__(self, cfg: HandsFreeConfig, voice_cfg: VoiceConfig) -> None:
        self._chain = cfg.stt_chain
        self._voice_cfg = voice_cfg
        self.last_provider = "none"
        self.device = "unloaded"

    def warm(self) -> None:
        if "faster_whisper" in self._chain:
            from ..stt.faster_whisper_local import load_model

            loaded = load_model(
                self._voice_cfg.whisper_model,
                self._voice_cfg.whisper_device,
                self._voice_cfg.whisper_compute_type,
            )
            self.device = loaded.device

    def transcribe(self, utt: Utterance) -> str:
        samples = utt.samples
        if utt.sample_rate != 16000:
            samples = resample(samples, utt.sample_rate, 16000)
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        for name in self._chain:
            try:
                if name == "faster_whisper":
                    from ..stt.faster_whisper_local import transcribe_audio

                    text, _c, _l, self.device = transcribe_audio(
                        samples,
                        size=self._voice_cfg.whisper_model,
                        device=self._voice_cfg.whisper_device,
                        compute_type=self._voice_cfg.whisper_compute_type,
                        language=self._voice_cfg.whisper_lang or None,
                        initial_prompt=_QUERY_PROMPT,
                    )
                elif name == "voicebox":
                    from ..voicebox import get_client

                    client = get_client()
                    if not client.health().get("ok"):
                        continue
                    text = client.transcribe(float_to_wav_bytes(samples, 16000), suffix=".wav")["text"]
                else:
                    continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("STT %s failed (%s); trying next", name, str(exc)[:160])
                continue
            self.last_provider = name
            return text.strip()
        self.last_provider = "none"
        raise RuntimeError("no STT engine available")


class HandsFreeAssistant:
    def __init__(
        self,
        *,
        cfg: HandsFreeConfig,
        source,
        wake: WakeDetector,
        transcriber: Transcriber,
        speaker: Speaker,
        bridge: CFOBridge,
        status: StatusFile,
    ) -> None:
        self.cfg = cfg
        self.source = source
        self.wake = wake
        self.transcriber = transcriber
        self.speaker = speaker
        self.bridge = bridge
        self.status = status
        self.sm = StateMachine(publisher=status, logger=logger)
        self.segmenter = Segmenter(
            sample_rate=cfg.sample_rate,
            frame_ms=cfg.frame_ms,
            silence_timeout=cfg.silence_timeout,
            max_seconds=cfg.max_record_seconds,
            aggressiveness=cfg.vad_aggressiveness,
        )
        self._deadline: float | None = None
        self._stop = threading.Event()
        #: Completed turns, for --simulate reporting and tests.
        self.turns: list[dict] = []

    # ---- lifecycle ------------------------------------------------------- #
    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        self.source.start()
        self.sm.to(VoiceState.LISTENING_FOR_WAKE_WORD, error=None)
        last_beat = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_beat >= HEARTBEAT_SECONDS:
                    self.status.heartbeat()
                    last_beat = now
                    if stop_request_path().exists():
                        stop_request_path().unlink(missing_ok=True)
                        logger.info("stop requested")
                        break
                self._tick(now)

                # A file is not real time: wait for speech to finish before
                # feeding the next utterance, or it would count as a barge-in.
                if not self.source.live and self.speaker.is_speaking():
                    time.sleep(0.03)
                    continue

                frame = self.source.read(timeout=0.1)
                if frame is None:
                    if self.source.exhausted and self._settled():
                        break
                    continue
                utterance = self.segmenter.feed(frame)
                if utterance is not None:
                    self._on_utterance(utterance)
        finally:
            self.speaker.stop()
            self.source.close()
            self.sm.to(VoiceState.IDLE)

    def _settled(self) -> bool:
        if self.speaker.is_speaking() or self.segmenter.in_speech:
            return False
        return self.sm.state in (VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.LISTENING)

    def _tick(self, now: float) -> None:
        state = self.sm.state
        if state == VoiceState.SPEAKING and not self.speaker.is_speaking():
            self._after_speaking()
        elif (
            state == VoiceState.LISTENING
            and self._deadline is not None
            and now > self._deadline
            and not self.segmenter.in_speech
        ):
            self._deadline = None
            self.sm.to(VoiceState.LISTENING_FOR_WAKE_WORD)

    def _listen(self, seconds: float) -> None:
        """Open a window where speech needs no wake word."""
        self.segmenter.reset()
        self.segmenter.max_seconds = self.cfg.max_record_seconds
        self.source.flush()
        if seconds <= 0:
            self._deadline = None
            self.sm.to(VoiceState.LISTENING_FOR_WAKE_WORD)
            return
        self._deadline = time.monotonic() + seconds
        self.sm.to(VoiceState.LISTENING)

    def _after_speaking(self) -> None:
        # The follow-up window starts now, so the conversation context must too.
        keep_alive = getattr(self.bridge, "keep_alive", None)
        if keep_alive is not None:
            keep_alive()
        # Flushing here drops the tail of Finzo's own voice picked up by the mic.
        self._listen(self.cfg.followup_seconds)

    # ---- utterances ------------------------------------------------------ #
    def _on_utterance(self, utt: Utterance) -> None:
        state = self.sm.state
        try:
            if state == VoiceState.SPEAKING:
                self._during_speech(utt)
            elif state == VoiceState.LISTENING_FOR_WAKE_WORD:
                result = self.wake.detect(utt)
                if self.cfg.debug:
                    logger.info("heard (wake probe): %r", result.text)
                if result.matched:
                    self._on_wake(utt, result.query)
            elif state == VoiceState.LISTENING:
                result = self.wake.detect(utt)
                if result.matched:
                    self._on_wake(utt, result.query)
                else:
                    self._question_from_audio(utt)
        except Exception:  # noqa: BLE001
            # One bad turn must never kill a background service.
            logger.exception("turn failed")
            self.sm.to(VoiceState.ERROR, error="internal error")
            self._say("Sorry, something went wrong on my side.")

    def _during_speech(self, utt: Utterance) -> None:
        """Only a wake word or a stop phrase may interrupt Finzo."""
        text = self.wake.probe(utt)
        if wake_text.is_stop_command(text):
            logger.info("barge-in: stop")
            self.speaker.stop()
            self.sm.to(VoiceState.INTERRUPTED)
            self._listen(self.cfg.followup_seconds)
            return
        match = wake_text.match_wake_word(text, wake_word=self.wake.name)
        if match:
            logger.info("barge-in: wake word")
            self.speaker.stop()
            self.sm.to(VoiceState.INTERRUPTED)
            self._on_wake(utt, match.query)
        # Anything else is Finzo hearing itself, or background speech.

    def _on_wake(self, utt: Utterance, fast_query: str) -> None:
        self.sm.to(VoiceState.WAKE_DETECTED)
        spoke_more = bool(fast_query) or utt.seconds > self.cfg.wake_probe_seconds + 0.3 or utt.truncated
        if spoke_more:
            # "Hey Finzo, how much did I spend on food?" in one breath: decode the
            # whole utterance with the accurate model and drop the wake phrase.
            self.sm.to(VoiceState.TRANSCRIBING)
            try:
                full = self.transcriber.transcribe(utt)
            except RuntimeError:
                self._say(MSG_STT_DOWN)
                return
            query = strip_leading_wake(full, self.wake.name) or fast_query
            if query.strip():
                self._answer(query)
                return
        # Bare "Hey Finzo": acknowledge, then listen for the question.
        if self.speaker.speak(ACK):
            self.speaker.wait(3.0)
        self._listen(self.cfg.listen_timeout)

    def _question_from_audio(self, utt: Utterance) -> None:
        self._deadline = None
        self.sm.to(VoiceState.TRANSCRIBING)
        try:
            text = self.transcriber.transcribe(utt)
        except RuntimeError:
            self._say(MSG_STT_DOWN)
            return
        if not text or len(wake_text.normalize(text)) < 2:
            self._say(MSG_NOT_UNDERSTOOD)
            return
        self._answer(text)

    def _answer(self, query: str) -> None:
        self.sm.to(VoiceState.THINKING, last_transcript=query)
        started = time.perf_counter()
        result = self.bridge.ask(query)
        elapsed = round((time.perf_counter() - started) * 1000)
        if result.get("action") == "stop":
            self.speaker.stop()
            self._listen(0)
            return
        speech = result.get("speech") or result.get("response") or MSG_NOT_UNDERSTOOD
        written = result.get("response") or speech
        self.turns.append(
            {
                "question": query,
                "answer": written,
                "speech": speech,
                "ok": bool(result.get("ok")),
                "intent": result.get("intent"),
                "llm_used": result.get("llm_used"),
                "stt": self.transcriber.last_provider,
                "think_ms": elapsed,
            }
        )
        # Lengths only in the log; the figures are the user's finances.
        logger.info(
            "answered ok=%s intent=%s llm=%s chars=%d in %dms",
            result.get("ok"), result.get("intent"), result.get("llm_used"), len(written), elapsed,
        )
        self._say(speech, last_response=written)

    def _say(self, text: str, **detail) -> None:
        self.source.flush()  # drop audio captured while transcribing and thinking
        self.segmenter.reset()
        self.sm.to(VoiceState.SPEAKING, error=None, **detail)
        # Short utterances while speaking keep barge-in responsive.
        self.segmenter.max_seconds = self.cfg.wake_probe_seconds
        if not self.speaker.speak(text):
            self._after_speaking()
