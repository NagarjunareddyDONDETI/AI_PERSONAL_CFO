"""Local wake-word detection behind a swappable interface.

The shipped implementation decodes only the first couple of seconds of each
VAD-gated utterance with a tiny Whisper model, then applies the SAME text matcher
the browser path uses (``voice.wake``). That means:

  - nothing is decoded while the room is silent (the VAD gates it),
  - "Hey Finzo, how much did I spend on food" works in one breath, because the
    trailing query is part of the same utterance, and
  - the false-activation rules (deny list, position anchoring, edit distance 1)
    are identical in both paths.

A dedicated keyword spotter (openWakeWord, Porcupine) would use less CPU while
idle. It only has to implement ``WakeDetector`` to replace this one.
"""
from __future__ import annotations

import abc
import logging
from dataclasses import dataclass

import numpy as np

from .. import wake as wake_text
from .audio import Utterance, resample

logger = logging.getLogger("voice.handsfree.wake")

# Biases Whisper toward spelling the name correctly. The name is deliberately NOT
# the first word: Whisper sometimes echoes its prompt on near-silence, and a
# hallucinated "The assistant is called Finzo" fails the position anchoring,
# where "Finzo ..." would trigger the assistant by itself.
_WAKE_PROMPT = "The assistant is called Finzo."


@dataclass(frozen=True)
class WakeResult:
    matched: bool
    text: str = ""
    #: Anything the fast model heard after the wake word.
    query: str = ""


class WakeDetector(abc.ABC):
    #: Name token the detector listens for, e.g. "finzo".
    name: str = "finzo"

    def warm(self) -> None:
        """Load models up front so the first wake is not slow."""

    @abc.abstractmethod
    def probe(self, utterance: Utterance) -> str:
        """Cheap transcription of the start of an utterance."""

    def detect(self, utterance: Utterance) -> WakeResult:
        text = self.probe(utterance)
        match = wake_text.match_wake_word(text, wake_word=self.name)
        return WakeResult(matched=bool(match), text=text, query=match.query if match else "")


class WhisperWakeDetector(WakeDetector):
    def __init__(
        self,
        *,
        phrase: str,
        model: str,
        device: str,
        compute_type: str,
        probe_seconds: float,
    ) -> None:
        self.name = wake_text.wake_name(phrase)
        self._model = model
        self._device = device
        self._compute_type = compute_type
        self._probe_seconds = probe_seconds
        # English-only checkpoints reject a language argument other than "en".
        self._language = "en"

    def warm(self) -> None:
        from ..stt.faster_whisper_local import load_model

        loaded = load_model(self._model, self._device, self._compute_type)
        logger.info("wake model %s on %s", self._model, loaded.device)

    def probe(self, utterance: Utterance) -> str:
        from ..stt.faster_whisper_local import transcribe_audio

        head = utterance.head(self._probe_seconds)
        if utterance.sample_rate != 16000:
            head = resample(head, utterance.sample_rate, 16000)
        if head.size < 1600:  # under 0.1 s: nothing to hear
            return ""
        text, _conf, _lang, _device = transcribe_audio(
            np.ascontiguousarray(head, dtype=np.float32),
            size=self._model,
            device=self._device,
            compute_type=self._compute_type,
            language=self._language,
            initial_prompt=_WAKE_PROMPT,
            beam_size=1,
            vad_filter=False,  # already VAD-gated upstream
        )
        return text


class AlwaysAwake(WakeDetector):
    """WAKE_WORD_ENABLED=false: every utterance is addressed to Finzo.

    Only sensible with a headset in a quiet room, since anything said nearby
    becomes a question. The probe still runs so stop commands keep working.
    """

    def __init__(self, inner: WakeDetector) -> None:
        self._inner = inner
        self.name = inner.name

    def warm(self) -> None:
        self._inner.warm()

    def probe(self, utterance: Utterance) -> str:
        return self._inner.probe(utterance)

    def detect(self, utterance: Utterance) -> WakeResult:
        text = self.probe(utterance)
        return WakeResult(matched=True, text=text, query=wake_text.strip_wake_word(text))


def strip_leading_wake(text: str, name: str) -> str:
    """Remove the wake phrase from an accurate transcript of the same utterance.

    The accurate model may spell the name differently from the fast one ("Fenzo",
    "Vinzo"), so this looks for a greeting and a near-match of the name within the
    first three words and cuts through it. Falls back to the exact matcher, then
    to the text unchanged: the pipeline copes with a stray "hey".
    """
    match = wake_text.match_wake_word(text, wake_word=name)
    if match:
        return match.query
    tokens = wake_text.normalize(text).split(" ")
    for i, token in enumerate(tokens[:3]):
        if token in {"hey", "hi", "hello", "ok", "okay", "hay"}:
            continue
        if wake_text._edit_distance(token, name, cap=2) <= 2:  # noqa: SLF001
            return " ".join(tokens[i + 1 :]).strip()
        break
    return wake_text.normalize(text)
