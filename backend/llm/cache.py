"""Response cache for the LLM layer.

In-memory TTL cache by default; transparently uses Redis when ``REDIS_URL`` is
set and the ``redis`` package is installed. Falls back to memory if Redis is
unavailable so a cache backend never takes down the app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Optional

from .base import LLMResponse, Message

logger = logging.getLogger("llm.cache")

_DEFAULT_MAX_CACHE_SIZE = int(os.getenv("MAX_LLM_CACHE_SIZE", "512"))


def make_key(
    messages: list[Message],
    *,
    temperature: float,
    max_tokens: int | None,
    provider_hint: str,
) -> str:
    """Deterministic cache key for a request (independent of which provider)."""
    payload = {
        "messages": [m.model_dump() for m in messages],
        "temperature": round(temperature, 4),
        "max_tokens": max_tokens,
        "hint": provider_hint,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return "llm:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class _MemoryCache:
    """Bounded in-process TTL cache with LRU eviction."""

    def __init__(self, max_size: int = _DEFAULT_MAX_CACHE_SIZE) -> None:
        self.max_size = max_size
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            item = self._store.get(key)
            if not item:
                return None
            expires_at, value = item
            if expires_at < time.time():
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return value

    def set(self, key: str, value: str, ttl: int) -> None:
        now = time.time()
        with self._lock:
            # Sweep expired entries periodically on writes
            expired = [k for k, (exp, _) in self._store.items() if exp < now]
            for k in expired:
                self._store.pop(k, None)

            self._store[key] = (now + ttl, value)
            self._store.move_to_end(key)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class ResponseCache:
    """Cache facade used by the router."""

    def __init__(self, ttl: int | None = None, redis_url: str | None = None, max_size: int | None = None):
        self.ttl = ttl if ttl is not None else int(os.getenv("LLM_CACHE_TTL", "900"))
        self._memory = _MemoryCache(max_size=max_size or _DEFAULT_MAX_CACHE_SIZE)
        self._redis = None
        url = redis_url if redis_url is not None else os.getenv("REDIS_URL", "")
        if url:
            self._try_redis(url)

    def _try_redis(self, url: str) -> None:
        try:
            import redis  # type: ignore

            self._redis = redis.Redis.from_url(url, decode_responses=True)
            self._redis.ping()
            logger.info("LLM cache using Redis at %s", url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis unavailable (%s); using in-memory cache", exc)
            self._redis = None

    def get(self, key: str) -> Optional[LLMResponse]:
        raw: Optional[str] = None
        if self._redis is not None:
            try:
                raw = self._redis.get(key)
            except Exception:  # noqa: BLE001
                raw = None
        if raw is None:
            raw = self._memory.get(key)
        if raw is None:
            return None
        try:
            resp = LLMResponse.model_validate_json(raw)
            resp.cached = True
            return resp
        except Exception:  # noqa: BLE001
            return None

    def set(self, key: str, response: LLMResponse) -> None:
        raw = response.model_dump_json()
        self._memory.set(key, raw, self.ttl)
        if self._redis is not None:
            try:
                self._redis.setex(key, self.ttl, raw)
            except Exception:  # noqa: BLE001
                pass

    def clear(self) -> None:
        self._memory.clear()
        if self._redis is not None:
            try:
                self._redis.flushdb()
            except Exception:  # noqa: BLE001
                pass
