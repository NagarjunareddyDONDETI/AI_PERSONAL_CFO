"""Audio in and out for the hands-free daemon.

``Segmenter`` is pure (bytes in, utterances out) so VAD behaviour is unit-tested
without a microphone. ``MicSource`` and ``FileSource`` produce identical 30 ms
int16 mono frames, which is what lets a recorded WAV drive the exact same loop
as a live microphone for end-to-end testing.

Raw microphone audio is never written to disk and never leaves the process.
"""
from __future__ import annotations

import collections
import io
import logging
import queue
import threading
import time
import wave
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger("voice.handsfree.audio")


# --------------------------------------------------------------------------- #
# WAV helpers
# --------------------------------------------------------------------------- #
def pcm16_to_float(pcm: bytes | np.ndarray) -> np.ndarray:
    arr = np.frombuffer(pcm, dtype=np.int16) if isinstance(pcm, (bytes, bytearray)) else pcm
    return arr.astype(np.float32) / 32768.0


def float_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return buf.getvalue()


def decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    """WAV bytes -> (mono float32 samples, sample rate). Handles 8/16/32-bit PCM."""
    with wave.open(io.BytesIO(data), "rb") as wav:
        channels = wav.getnchannels()
        width = wav.getsampwidth()
        rate = wav.getframerate()
        raw = wav.readframes(wav.getnframes())
    if width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"Unsupported WAV sample width: {width * 8} bits")
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resample. Plenty for speech headed to Whisper; avoids a scipy import."""
    if src_rate == dst_rate or samples.size == 0:
        return samples.astype(np.float32)
    duration = samples.size / src_rate
    n_out = max(1, int(round(duration * dst_rate)))
    x_old = np.linspace(0.0, duration, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, duration, num=n_out, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


# --------------------------------------------------------------------------- #
# Voice activity detection
# --------------------------------------------------------------------------- #
class _WebRtcVad:
    def __init__(self, aggressiveness: int, sample_rate: int) -> None:
        import webrtcvad

        self._vad = webrtcvad.Vad(aggressiveness)
        self._rate = sample_rate

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, self._rate)


class _EnergyVad:
    """Fallback when webrtcvad is missing: RMS against an adaptive noise floor."""

    def __init__(self) -> None:
        self._floor = 200.0

    def is_speech(self, frame: bytes) -> bool:
        pcm = np.frombuffer(frame, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(pcm * pcm))) if pcm.size else 0.0
        speech = rms > max(450.0, self._floor * 3.0)
        if not speech:
            # Track the room slowly so a fan or AC does not read as speech.
            self._floor = 0.95 * self._floor + 0.05 * rms
        return speech


def make_vad(aggressiveness: int, sample_rate: int):
    try:
        return _WebRtcVad(aggressiveness, sample_rate)
    except Exception as exc:  # noqa: BLE001
        logger.warning("webrtcvad unavailable (%s); using energy-based VAD", exc)
        return _EnergyVad()


@dataclass
class Utterance:
    samples: np.ndarray  # float32 mono at the source sample rate
    sample_rate: int
    #: True when cut by the length cap rather than by the speaker pausing.
    truncated: bool = False

    @property
    def seconds(self) -> float:
        return self.samples.size / self.sample_rate

    def head(self, seconds: float) -> np.ndarray:
        return self.samples[: int(seconds * self.sample_rate)]


class Segmenter:
    """Frames in, complete utterances out.

    Starts once most of a short window is voiced (so a click is not speech), keeps
    a pre-roll so the first syllable is not clipped, and ends after
    ``silence_timeout`` of continuous silence or at ``max_seconds``.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        frame_ms: int = 30,
        silence_timeout: float = 1.2,
        max_seconds: float = 20.0,
        min_seconds: float = 0.35,
        aggressiveness: int = 2,
        vad=None,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self._vad = vad or make_vad(aggressiveness, sample_rate)
        self._silence_frames = max(1, int(silence_timeout * 1000 / frame_ms))
        self.max_seconds = max_seconds
        self._min_frames = max(1, int(min_seconds * 1000 / frame_ms))
        self._start_window = collections.deque(maxlen=8)  # ~240 ms
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=10)  # 300 ms
        self.reset()

    def reset(self) -> None:
        self._frames: list[bytes] = []
        self._voiced_frames = 0
        self._silent_run = 0
        self.in_speech = False
        self._start_window.clear()
        self._preroll.clear()

    def feed(self, frame: bytes) -> Utterance | None:
        try:
            voiced = self._vad.is_speech(frame)
        except Exception:  # noqa: BLE001 - malformed frame: treat as silence
            voiced = False

        if not self.in_speech:
            self._preroll.append(frame)
            self._start_window.append(voiced)
            if sum(self._start_window) >= 5:
                self.in_speech = True
                self._frames = list(self._preroll)
                self._voiced_frames = sum(self._start_window)
                self._silent_run = 0
            return None

        self._frames.append(frame)
        if voiced:
            self._voiced_frames += 1
            self._silent_run = 0
        else:
            self._silent_run += 1

        max_frames = int(self.max_seconds * 1000 / self.frame_ms)
        if self._silent_run >= self._silence_frames or len(self._frames) >= max_frames:
            truncated = len(self._frames) >= max_frames
            frames, voiced_count = self._frames, self._voiced_frames
            self.reset()
            if voiced_count < self._min_frames:
                return None  # a cough or a door, not a sentence
            pcm = b"".join(frames)
            return Utterance(pcm16_to_float(pcm), self.sample_rate, truncated=truncated)
        return None


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
class MicSource:
    """Live microphone at 16 kHz mono int16, delivered as fixed-size frames."""

    live = True

    def __init__(self, *, sample_rate: int, frame_samples: int, device: str = "") -> None:
        import sounddevice as sd

        self._sd = sd
        self.sample_rate = sample_rate
        self._frame_bytes = frame_samples * 2
        # ~15 s of backlog. If the loop stalls longer than that, old audio is
        # dropped: it is stale anyway, and memory must not grow without bound.
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=500)
        self._pending = b""
        self._lock = threading.Lock()
        device_arg: int | str | None = None
        if device:
            device_arg = int(device) if device.isdigit() else device
        self._stream = sd.RawInputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=frame_samples,
            device=device_arg,
            callback=self._callback,
        )

    def _callback(self, indata, _frames, _time, status) -> None:
        if status:
            logger.debug("mic status: %s", status)
        with self._lock:
            self._pending += bytes(indata)
            while len(self._pending) >= self._frame_bytes:
                frame, self._pending = (
                    self._pending[: self._frame_bytes],
                    self._pending[self._frame_bytes :],
                )
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._queue.put_nowait(frame)

    def start(self) -> None:
        self._stream.start()

    def close(self) -> None:
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass

    def read(self, timeout: float = 0.1) -> bytes | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def flush(self) -> None:
        """Drop everything captured so far, e.g. audio recorded while thinking."""
        with self._lock:
            self._pending = b""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    @property
    def exhausted(self) -> bool:
        return False


class FileSource:
    """A WAV file played into the loop as if it were a microphone.

    Used by ``--simulate`` and the end-to-end tests. Trailing silence is appended
    so the final utterance ends the way a real pause would end it.
    """

    live = False

    def __init__(self, path: str, *, sample_rate: int, frame_samples: int, tail_seconds: float = 2.0) -> None:
        with open(path, "rb") as fh:
            samples, rate = decode_wav(fh.read())
        samples = resample(samples, rate, sample_rate)
        samples = np.concatenate([samples, np.zeros(int(tail_seconds * sample_rate), np.float32)])
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        step = frame_samples * 2
        self._frames = [pcm[i : i + step] for i in range(0, len(pcm) - step + 1, step)]
        self._index = 0
        self.sample_rate = sample_rate

    def start(self) -> None:
        pass

    def close(self) -> None:
        pass

    def read(self, timeout: float = 0.1) -> bytes | None:
        if self._index >= len(self._frames):
            time.sleep(min(timeout, 0.02))
            return None
        frame = self._frames[self._index]
        self._index += 1
        return frame

    def flush(self) -> None:
        # A file has no "audio that arrived while thinking"; keep reading in order.
        pass

    @property
    def exhausted(self) -> bool:
        return self._index >= len(self._frames)


def list_input_devices() -> list[dict]:
    import sounddevice as sd

    devices = []
    default_in = sd.default.device[0] if sd.default.device else None
    for idx, dev in enumerate(sd.query_devices()):
        if dev.get("max_input_channels", 0) > 0:
            devices.append(
                {
                    "index": idx,
                    "name": dev.get("name"),
                    "default_samplerate": dev.get("default_samplerate"),
                    "default": idx == default_in,
                }
            )
    return devices
