"""Hands-free state machine and the status file that publishes it.

The daemon is a separate process from the API server, so state is shared through
a small JSON file rather than memory. Writes are atomic (temp file + replace) so a
reader never sees half a document, and the file carries a heartbeat so a crashed
daemon is reported as stopped rather than frozen in "SPEAKING" forever.
"""
from __future__ import annotations

import enum
import json
import os
import threading
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[2]

#: The daemon refreshes the file at least this often while running.
HEARTBEAT_SECONDS = 2.0
#: Older than this and the daemon is considered gone.
STALE_AFTER_SECONDS = 10.0


class VoiceState(str, enum.Enum):
    IDLE = "IDLE"
    LISTENING_FOR_WAKE_WORD = "LISTENING_FOR_WAKE_WORD"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


# Legal transitions. Anything not listed is ignored with a log line rather than
# raising: audio callbacks and playback completion genuinely arrive out of order.
_ALLOWED: dict[VoiceState, set[VoiceState]] = {
    VoiceState.IDLE: {VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.ERROR},
    VoiceState.LISTENING_FOR_WAKE_WORD: {
        VoiceState.WAKE_DETECTED, VoiceState.LISTENING, VoiceState.IDLE, VoiceState.ERROR,
    },
    VoiceState.WAKE_DETECTED: {
        VoiceState.LISTENING, VoiceState.TRANSCRIBING, VoiceState.SPEAKING,
        VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.ERROR,
    },
    VoiceState.LISTENING: {
        VoiceState.TRANSCRIBING, VoiceState.LISTENING_FOR_WAKE_WORD,
        VoiceState.WAKE_DETECTED, VoiceState.ERROR,
    },
    VoiceState.TRANSCRIBING: {
        VoiceState.THINKING, VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.SPEAKING,
        VoiceState.ERROR,
    },
    VoiceState.THINKING: {
        VoiceState.SPEAKING, VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.ERROR,
    },
    VoiceState.SPEAKING: {
        VoiceState.INTERRUPTED, VoiceState.LISTENING, VoiceState.LISTENING_FOR_WAKE_WORD,
        VoiceState.ERROR,
    },
    VoiceState.INTERRUPTED: {
        VoiceState.WAKE_DETECTED, VoiceState.LISTENING, VoiceState.TRANSCRIBING,
        VoiceState.LISTENING_FOR_WAKE_WORD, VoiceState.ERROR,
    },
    # ERROR must be able to speak its apology and go back to listening; a state
    # that can only be left for "wake word" would strand a failed turn.
    VoiceState.ERROR: {
        VoiceState.SPEAKING, VoiceState.LISTENING, VoiceState.LISTENING_FOR_WAKE_WORD,
        VoiceState.IDLE,
    },
}


def state_dir() -> Path:
    raw = (os.getenv("FINZO_VOICE_STATE_DIR") or "").strip()
    path = Path(raw).expanduser() if raw else _BACKEND_DIR / ".finzo"
    path.mkdir(parents=True, exist_ok=True)
    return path


def status_path() -> Path:
    return state_dir() / "voice_status.json"


def stop_request_path() -> Path:
    return state_dir() / "voice_stop.request"


class StateMachine:
    """Single owner of the daemon's state. Thread-safe."""

    def __init__(self, *, publisher: "StatusFile | None" = None, logger=None) -> None:
        self._state = VoiceState.IDLE
        self._lock = threading.Lock()
        self._publisher = publisher
        self._logger = logger
        self.detail: dict = {}

    @property
    def state(self) -> VoiceState:
        return self._state

    def to(self, new: VoiceState, **detail) -> bool:
        with self._lock:
            old = self._state
            if new == old:
                self.detail.update(detail)
                accepted = True
            # Shutdown and faults can happen mid-turn, from any state.
            elif new in _ALLOWED[old] or new in (VoiceState.IDLE, VoiceState.ERROR):
                self._state = new
                self.detail.update(detail)
                accepted = True
            else:
                accepted = False
        if not accepted:
            if self._logger:
                self._logger.debug("ignored transition %s -> %s", old.value, new.value)
            return False
        if self._logger and new != old:
            self._logger.info("state %s -> %s", old.value, new.value)
        if self._publisher:
            self._publisher.publish(self._state, self.detail)
        return True


class StatusFile:
    """Atomic JSON status document shared with the API server."""

    def __init__(self, path: Path | None = None, *, static: dict | None = None) -> None:
        self.path = path or status_path()
        self._static = static or {}
        self._lock = threading.Lock()
        self._last: tuple[VoiceState, dict] = (VoiceState.IDLE, {})

    def publish(self, state: VoiceState, detail: dict | None = None) -> None:
        with self._lock:
            self._last = (state, dict(detail or {}))
            doc = {
                **self._static,
                **self._last[1],
                "state": state.value,
                "pid": os.getpid(),
                "updated_at": time.time(),
            }
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, default=str), encoding="utf-8")
            os.replace(tmp, self.path)

    def heartbeat(self) -> None:
        state, detail = self._last
        self.publish(state, detail)

    def clear(self) -> None:
        with self._lock:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def read_status(path: Path | None = None) -> dict:
    """What the API reports. Never raises."""
    path = path or status_path()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, OSError):
        return {"running": False, "state": VoiceState.IDLE.value}
    age = time.time() - float(doc.get("updated_at") or 0)
    doc["running"] = age < STALE_AFTER_SECONDS
    doc["age_seconds"] = round(age, 1)
    if not doc["running"]:
        doc["state"] = VoiceState.IDLE.value
    return doc
