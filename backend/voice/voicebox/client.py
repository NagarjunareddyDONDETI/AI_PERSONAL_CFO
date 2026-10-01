"""HTTP client for a local Voicebox server.

The ONLY module in Finzo that knows Voicebox's wire format. Endpoints and schemas
were taken from Voicebox's own source (backend/routes/*.py, backend/models.py),
not guessed:

    GET  /health            -> HealthResponse {status: "healthy", gpu_available, ...}
    GET  /profiles          -> [VoiceProfileResponse {id, name, language, ...}]
    POST /transcribe        multipart: file, language?, model?  -> {text, duration}
                            202 while the Whisper model is still downloading
    POST /generate/stream   JSON GenerationRequest -> audio/wav bytes

``/generate/stream`` is used rather than ``/generate`` on purpose. ``/generate``
queues a job, returns immediately, and needs an SSE poll plus a second request to
``/audio/{id}`` to fetch the result, and it also writes every answer into
Voicebox's generation history. The stream route returns the WAV in one call and
stores nothing, which matters when the text is somebody's bank balance.

Every public method raises a ``VoiceboxError`` subclass on failure. The STT/TTS
providers translate those into the registries' never-raise result objects.
"""
from __future__ import annotations

import logging
import threading
import time

import httpx

from .config import ENGINES, STT_MODELS, VoiceboxConfig, load_config

logger = logging.getLogger("voice.voicebox")

# Voicebox caps GenerationRequest.text at 50k chars; a spoken answer is a few
# hundred. Bounding it here stops a runaway answer from pinning the GPU.
_MAX_TTS_CHARS = 5000


class VoiceboxError(Exception):
    """Base for every Voicebox failure."""

    code = "VOICEBOX_ERROR"


class VoiceboxUnavailable(VoiceboxError):
    """Not running, not reachable, disabled, or timed out."""

    code = "VOICEBOX_UNAVAILABLE"


class VoiceboxNotReady(VoiceboxError):
    """Running, but cannot serve this request yet (model downloading, no profile)."""

    code = "VOICEBOX_NOT_READY"


class VoiceboxBadResponse(VoiceboxError):
    """Answered, but with something we cannot use."""

    code = "VOICEBOX_BAD_RESPONSE"


def _detail(resp: httpx.Response) -> str:
    """Pull FastAPI's ``detail`` out of an error body, bounded for logs."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    detail = body.get("detail") if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("message") or detail
    return str(detail)[:200]


class VoiceboxClient:
    def __init__(
        self,
        config: VoiceboxConfig | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config or load_config()
        self._transport = transport
        self._lock = threading.Lock()
        self._health_cache: tuple[float, dict] | None = None
        self._profile_cache: tuple[float, str] | None = None
        self._refreshing = False
        if self.config.enabled and not self.config.is_loopback:
            logger.warning(
                "VOICEBOX_BASE_URL is not on this machine (%s): spoken answers, "
                "which contain financial figures, will be sent over the network.",
                self.config.base_url,
            )

    # ---- transport ------------------------------------------------------- #
    def _client(self, timeout: float | None = None) -> httpx.Client:
        # A loopback connect either succeeds in well under a millisecond or is
        # refused, so a short connect timeout only cuts off the Windows retry wait.
        connect = 0.5 if self.config.is_loopback else 5.0
        return httpx.Client(
            base_url=self.config.base_url,
            timeout=httpx.Timeout(timeout or self.config.timeout_seconds, connect=connect),
            transport=self._transport,
        )

    def _request(self, method: str, path: str, *, timeout: float | None = None, **kw) -> httpx.Response:
        if not self.config.enabled:
            raise VoiceboxUnavailable("Voicebox is disabled (VOICEBOX_ENABLED=false).")
        try:
            with self._client(timeout) as client:
                return client.request(method, path, **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The ordinary "Voicebox app is not open" case.
            raise VoiceboxUnavailable(
                f"Cannot reach Voicebox at {self.config.base_url}. Is the Voicebox app running?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise VoiceboxUnavailable(f"Voicebox timed out on {path}") from exc
        except httpx.HTTPError as exc:
            # Connection refused is the normal "app is closed" case.
            raise VoiceboxUnavailable(
                f"Cannot reach Voicebox at {self.config.base_url} ({type(exc).__name__})"
            ) from exc

    @staticmethod
    def _json(resp: httpx.Response, path: str):
        try:
            return resp.json()
        except ValueError as exc:
            raise VoiceboxBadResponse(f"{path} returned non-JSON") from exc

    # ---- health ---------------------------------------------------------- #
    def health(self, *, use_cache: bool = True) -> dict:
        """Probe the server. Never raises: returns ``{ok: False, error}`` instead.

        Cached for a few seconds because the registries ask "is Voicebox up?" on
        every request, and a closed app should cost a refused connect, not a hang.
        """
        now = time.monotonic()
        with self._lock:
            cached = self._health_cache
        if use_cache and cached and now - cached[0] < self.config.health_ttl_seconds:
            return cached[1]

        started = time.perf_counter()
        result: dict
        try:
            resp = self._request("GET", "/health", timeout=3.0)
            if resp.status_code != 200:
                raise VoiceboxBadResponse(f"/health http {resp.status_code}")
            body = self._json(resp, "/health")
            if not isinstance(body, dict):
                raise VoiceboxBadResponse("/health body is not an object")
            status = body.get("status")
            result = {
                "ok": status == "healthy",
                "status": status,
                "gpu_available": body.get("gpu_available"),
                "gpu_type": body.get("gpu_type"),
                "backend_type": body.get("backend_type"),
                "model_loaded": body.get("model_loaded"),
                "error": None if status == "healthy" else f"status={status!r}",
            }
        except VoiceboxError as exc:
            result = {"ok": False, "status": None, "error": str(exc), "code": exc.code}
        except Exception as exc:  # noqa: BLE001
            # A health probe must never be what takes a request down, whatever the
            # transport throws (including test doubles that refuse unmocked hosts).
            result = {
                "ok": False, "status": None, "code": VoiceboxUnavailable.code,
                "error": f"health probe failed ({type(exc).__name__})",
            }
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["base_url"] = self.config.base_url
        with self._lock:
            self._health_cache = (now, result)
        return result

    def is_up(self) -> bool:
        """Non-blocking availability check for the provider registries.

        Returns the last known answer and refreshes it in the background once it is
        stale. On Windows a refused loopback connect takes about two seconds
        (the stack retries the SYN), so probing inline would add that to every
        voice request whenever Voicebox is closed. The cost is that the first
        request after Voicebox starts may still go to the fallback provider.
        """
        if not self.config.enabled:
            return False
        with self._lock:
            cached = self._health_cache
            fresh = cached and time.monotonic() - cached[0] < self.config.health_ttl_seconds
            if not fresh and not self._refreshing:
                self._refreshing = True
                threading.Thread(target=self._refresh, name="voicebox-health", daemon=True).start()
        return bool(cached and cached[1].get("ok"))

    def _refresh(self) -> None:
        try:
            self.health(use_cache=False)
        finally:
            with self._lock:
                self._refreshing = False

    # ---- profiles -------------------------------------------------------- #
    def list_profiles(self) -> list[dict]:
        resp = self._request("GET", "/profiles", timeout=10.0)
        if resp.status_code != 200:
            raise VoiceboxBadResponse(f"/profiles http {resp.status_code}: {_detail(resp)}")
        body = self._json(resp, "/profiles")
        if not isinstance(body, list):
            raise VoiceboxBadResponse("/profiles did not return a list")
        return [p for p in body if isinstance(p, dict) and p.get("id")]

    def resolve_profile_id(self) -> str:
        """Turn VOICEBOX_VOICE_ID (an id or a profile name) into a profile id."""
        wanted = self.config.voice_id
        if not wanted:
            raise VoiceboxNotReady(
                "VOICEBOX_VOICE_ID is not set. Create a voice profile in Voicebox "
                "and put its name or id in backend/.env."
            )
        now = time.monotonic()
        with self._lock:
            cached = self._profile_cache
        if cached and now - cached[0] < 300:
            return cached[1]

        profiles = self.list_profiles()
        match = next((p for p in profiles if p["id"] == wanted), None)
        if match is None:
            lowered = wanted.lower()
            match = next(
                (p for p in profiles if str(p.get("name", "")).lower() == lowered), None
            )
        if match is None:
            names = ", ".join(sorted(str(p.get("name")) for p in profiles)) or "none"
            raise VoiceboxNotReady(
                f"No Voicebox profile matches VOICEBOX_VOICE_ID={wanted!r}. "
                f"Available: {names}"
            )
        with self._lock:
            self._profile_cache = (now, match["id"])
        return match["id"]

    # ---- speech to text -------------------------------------------------- #
    def transcribe(self, audio: bytes, *, suffix: str = ".wav") -> dict:
        """Return ``{text, duration}``."""
        if not audio:
            raise VoiceboxBadResponse("Empty audio.")
        data: dict[str, str] = {}
        language = self.config.stt_language()
        if language:
            data["language"] = language
        if self.config.stt_model in STT_MODELS:
            data["model"] = self.config.stt_model
        files = {"file": (f"audio{suffix}", audio, "application/octet-stream")}

        resp = self._request("POST", "/transcribe", files=files, data=data)
        if resp.status_code == 202:
            raise VoiceboxNotReady(
                "Voicebox is downloading its Whisper model. Try again in a minute."
            )
        if resp.status_code != 200:
            raise VoiceboxBadResponse(f"/transcribe http {resp.status_code}: {_detail(resp)}")
        body = self._json(resp, "/transcribe")
        if not isinstance(body, dict) or not isinstance(body.get("text"), str):
            raise VoiceboxBadResponse("/transcribe response has no text field")
        return {"text": body["text"].strip(), "duration": body.get("duration")}

    # ---- text to speech -------------------------------------------------- #
    def synthesize(self, text: str) -> bytes:
        """Return WAV bytes for ``text`` in the configured voice."""
        text = (text or "").strip()
        if not text:
            raise VoiceboxBadResponse("Nothing to speak.")
        payload: dict = {
            "profile_id": self.resolve_profile_id(),
            "text": text[:_MAX_TTS_CHARS],
            "language": self.config.tts_language(),
            "normalize": True,
            # Explicitly off: a persona rewrite runs Voicebox's own LLM over the
            # text and could reword a verified figure.
            "personality": False,
        }
        if self.config.engine in ENGINES:
            payload["engine"] = self.config.engine
        if self.config.instruct:
            payload["instruct"] = self.config.instruct[:500]

        resp = self._request("POST", "/generate/stream", json=payload)
        if resp.status_code == 400 and "not downloaded" in _detail(resp).lower():
            # /generate/stream never downloads a model; only the app (or the
            # queued /generate route) does. Observed on Voicebox 0.5.0 with a
            # fresh Kokoro profile.
            raise VoiceboxNotReady(
                "Voicebox has not downloaded this voice's model yet. Open Voicebox, "
                "select the Finzo profile and generate any short sentence once."
            )
        if resp.status_code == 404:
            with self._lock:
                self._profile_cache = None  # profile was deleted; re-resolve next time
            raise VoiceboxNotReady(f"Voicebox profile not found: {_detail(resp)}")
        if resp.status_code != 200:
            raise VoiceboxBadResponse(f"/generate/stream http {resp.status_code}: {_detail(resp)}")
        audio = resp.content
        if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
            raise VoiceboxBadResponse(
                f"/generate/stream did not return WAV audio "
                f"(content-type={resp.headers.get('content-type')}, {len(audio)} bytes)"
            )
        return audio


_client: VoiceboxClient | None = None
_client_lock = threading.Lock()


def get_client() -> VoiceboxClient:
    """Process-wide client, so health and profile caches are shared."""
    global _client
    with _client_lock:
        if _client is None:
            _client = VoiceboxClient()
        return _client
