"""faster-whisper STT provider (fully offline, CTranslate2, no torch).

Device handling is the part that matters on a Windows laptop GPU:

  - ``ctranslate2`` can LOAD a model onto CUDA and only fail on the first
    inference, when cuBLAS/cuDNN DLLs turn out to be missing. So a model is only
    accepted after a real warm-up inference, never on load alone.
  - Out-of-memory, or any CUDA runtime error mid-transcription, reloads the
    model on the CPU and retries that same clip once. The app never crashes
    because of the GPU.

Models are cached per (size, device) for the life of the process and shared by
every caller, so the hands-free daemon and this provider never load one twice.
"""
from __future__ import annotations

import io
import logging
import math
import threading
import time
from dataclasses import dataclass

from ..config import VoiceConfig
from .base import STTProvider, STTResult
from .whisper_local import _INITIAL_PROMPT

logger = logging.getLogger("voice.stt.faster_whisper")

_GPU_ERROR_MARKERS = ("cuda", "cublas", "cudnn", "out of memory", "gpu", "device")


@dataclass
class LoadedModel:
    model: object
    size: str
    device: str
    compute_type: str
    lock: threading.Lock


_models: dict[str, LoadedModel] = {}
_models_lock = threading.Lock()
_import_error: str | None = None
#: Set after the first CUDA failure in this process. Retrying CUDA after a failed
#: attempt is not just slow: with cuBLAS missing, a SECOND CUDA model load in the
#: same process was observed to hang indefinitely instead of raising. So CUDA is
#: tried at most once per process, and everything after that goes to the CPU.
_cuda_broken: str | None = None


def faster_whisper_installed() -> bool:
    global _import_error
    try:
        import faster_whisper  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        _import_error = str(exc)
        return False
    return True


def cuda_device_count() -> int:
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # noqa: BLE001
        return 0


def _looks_like_gpu_failure(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _GPU_ERROR_MARKERS)


def _warm_up(model) -> None:
    """One real inference. This is what exposes missing CUDA DLLs."""
    import numpy as np

    segments, _info = model.transcribe(np.zeros(16000, dtype=np.float32), beam_size=1)
    list(segments)  # transcribe() is lazy; consuming it runs the model


def _try_load(size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    model = WhisperModel(size, device=device, compute_type=compute_type)
    _warm_up(model)
    return model


def load_model(size: str, device: str = "auto", compute_type: str = "int8") -> LoadedModel:
    """Return a warmed model, choosing the best device that actually works.

    Order for ``auto``: CUDA at the requested precision, CUDA at int8, then CPU at
    int8. CPU int8 is the floor and is always attempted last.
    """
    key = f"{size}|{device}|{compute_type}"
    with _models_lock:
        if key in _models:
            return _models[key]

        global _cuda_broken
        attempts: list[tuple[str, str]] = []
        if device in ("auto", "cuda") and cuda_device_count() > 0 and _cuda_broken is None:
            attempts.append(("cuda", compute_type))
            if compute_type != "int8":
                attempts.append(("cuda", "int8"))
        if device in ("auto", "cpu") or not attempts:
            # float16 is GPU-only; CPU always runs int8.
            attempts.append(("cpu", "int8" if compute_type in ("float16", "int8_float16") else compute_type))

        last_error: Exception | None = None
        for dev, ctype in attempts:
            started = time.perf_counter()
            if dev == "cuda" and _cuda_broken is not None:
                continue  # an earlier attempt in this loop already broke CUDA
            try:
                model = _try_load(size, dev, ctype)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if dev == "cuda":
                    _cuda_broken = str(exc)[:200]
                logger.warning(
                    "faster-whisper %s on %s/%s unusable (%s); trying next option",
                    size, dev, ctype, str(exc)[:160],
                )
                continue
            loaded = LoadedModel(model, size, dev, ctype, threading.Lock())
            _models[key] = loaded
            logger.info(
                "faster-whisper %s ready on %s/%s in %.1fs",
                size, dev, ctype, time.perf_counter() - started,
            )
            return loaded
        raise RuntimeError(f"Could not load faster-whisper '{size}': {last_error}")


def cuda_status() -> str:
    """Human-readable GPU state for selftest and status."""
    if _cuda_broken:
        return f"unusable, using CPU ({_cuda_broken})"
    count = cuda_device_count()
    return f"{count} device(s)" if count else "none, using CPU"


def _force_cpu(loaded: LoadedModel, key: str) -> LoadedModel:
    """Swap a failing GPU model for a CPU one, releasing the GPU copy."""
    global _cuda_broken
    _cuda_broken = _cuda_broken or "runtime error during transcription"
    logger.warning("faster-whisper %s: GPU failed at runtime, moving to CPU", loaded.size)
    cpu = _try_load(loaded.size, "cpu", "int8")
    replacement = LoadedModel(cpu, loaded.size, "cpu", "int8", threading.Lock())
    with _models_lock:
        _models[key] = replacement
    del loaded.model  # drop the reference so CTranslate2 can free VRAM
    return replacement


def transcribe_audio(
    audio,
    *,
    size: str,
    device: str = "auto",
    compute_type: str = "int8",
    language: str | None = "en",
    initial_prompt: str | None = _INITIAL_PROMPT,
    beam_size: int = 5,
    vad_filter: bool = True,
) -> tuple[str, float, str | None, str]:
    """Transcribe bytes, a file-like object, or 16 kHz float32 samples.

    Returns ``(text, confidence, language, device_used)``.
    """
    key = f"{size}|{device}|{compute_type}"
    loaded = load_model(size, device, compute_type)
    source = io.BytesIO(audio) if isinstance(audio, (bytes, bytearray)) else audio

    for attempt in (1, 2):
        try:
            with loaded.lock:
                segments, info = loaded.model.transcribe(
                    source,
                    language=language or None,
                    beam_size=beam_size,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt=initial_prompt,
                    vad_filter=vad_filter,
                )
                segs = list(segments)
            break
        except Exception as exc:  # noqa: BLE001
            if attempt == 1 and loaded.device == "cuda" and _looks_like_gpu_failure(exc):
                loaded = _force_cpu(loaded, key)
                if isinstance(source, io.BytesIO):
                    source.seek(0)
                continue
            raise

    text = " ".join(s.text.strip() for s in segs).strip()
    if segs:
        avg = sum(s.avg_logprob for s in segs) / len(segs)
        try:
            confidence = max(0.0, min(1.0, math.exp(avg)))
        except OverflowError:
            confidence = 0.0
    else:
        confidence = 0.0
    return text, round(confidence, 3), getattr(info, "language", language), loaded.device


class FasterWhisperProvider(STTProvider):
    name = "faster_whisper"
    offline = True

    def __init__(self, config: VoiceConfig) -> None:
        self._config = config
        self._failed = False

    def is_available(self) -> bool:
        return not self._failed and faster_whisper_installed()

    def preload(self) -> bool:
        try:
            load_model(
                self._config.whisper_model,
                self._config.whisper_device,
                self._config.whisper_compute_type,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("faster-whisper preload failed: %s", exc)
            return False

    def transcribe(self, audio_bytes: bytes, suffix: str = ".webm") -> STTResult:
        if not audio_bytes:
            return STTResult(text="", provider=self.name, error="empty audio")
        started = time.perf_counter()
        try:
            text, confidence, language, device = transcribe_audio(
                audio_bytes,
                size=self._config.whisper_model,
                device=self._config.whisper_device,
                compute_type=self._config.whisper_compute_type,
                language=self._config.whisper_lang or None,
            )
        except RuntimeError as exc:
            # Model could not load anywhere (missing weights offline, etc.).
            # Stop advertising the provider instead of retrying every request.
            self._failed = True
            logger.warning("faster-whisper disabled: %s", exc)
            return STTResult(text="", provider=self.name, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            # Undecodable audio and similar per-clip problems.
            logger.warning("faster-whisper transcribe error: %s", str(exc)[:200])
            return STTResult(text="", provider=self.name, error=str(exc)[:200])
        latency = (time.perf_counter() - started) * 1000
        logger.info(
            "faster_whisper ok chars=%d conf=%.2f device=%s %.0fms",
            len(text), confidence, device, latency,
        )
        return STTResult(
            text=text,
            confidence=confidence,
            language=language,
            provider=self.name,
            latency_ms=round(latency, 1),
        )
