"""Fixed-window rate limiter for credential endpoints.

Without this, /auth/login is an offline-speed password oracle. PBKDF2 at 600k
iterations already makes each guess expensive, but that cost lands on our CPU,
so unlimited attempts are a denial-of-service vector as well as a brute-force one.

In-process only. With multiple uvicorn workers each worker keeps its own
counters, so the effective limit is (limit x workers) — put a real limiter at the
proxy or use Redis if you run more than one worker.
"""
from __future__ import annotations

import threading
import time
from collections import deque

# Keep at most this many distinct keys, evicting the least recently touched, so
# an attacker rotating identifiers cannot grow the table without bound.
_MAX_KEYS = 4096


class RateLimiter:
    def __init__(self, *, max_attempts: int = 8, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        cutoff = now - self.window_seconds
        while hits and hits[0] < cutoff:
            hits.popleft()
        return hits

    def check(self, key: str) -> int:
        """Return seconds to wait, or 0 when the caller may proceed."""
        now = time.time()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) < self.max_attempts:
                return 0
            return max(1, int(hits[0] + self.window_seconds - now))

    def record_failure(self, key: str) -> None:
        """Count one failed attempt against ``key``."""
        now = time.time()
        with self._lock:
            hits = self._prune(key, now)
            hits.append(now)
            if len(self._hits) > _MAX_KEYS:
                # dict preserves insertion order; drop the oldest entries.
                for stale in list(self._hits)[: len(self._hits) - _MAX_KEYS]:
                    self._hits.pop(stale, None)

    def reset(self, key: str) -> None:
        """Clear a key's history — called after a successful login."""
        with self._lock:
            self._hits.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# Shared limiters.
#   login: keyed on ip+email, counts failures only, so a legitimate user typing
#          one password wrong is unaffected once they succeed.
#   register: keyed on ip, counts every attempt, capping both account-creation
#          volume and the use of 409s to probe which emails exist. Set with a
#          shared office NAT in mind — 10/hour is generous for real signups.
login_limiter = RateLimiter(max_attempts=8, window_seconds=300)
register_limiter = RateLimiter(max_attempts=10, window_seconds=3600)
