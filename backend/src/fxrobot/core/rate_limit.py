"""Sliding-window rate limiter.

In-process only: correct for a single backend process. When the API is
scaled horizontally this must move to a shared store (e.g. Redis) — see
docs/ROADMAP.md.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowRateLimiter:
    def __init__(
        self,
        max_attempts: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self.window_seconds:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return self._hits.setdefault(key, deque())
        return hits

    def retry_after(self, key: str) -> int:
        """Seconds until `key` may try again (0 when not limited)."""
        with self._lock:
            now = self._clock()
            hits = self._prune(key, now)
            if len(hits) < self.max_attempts:
                return 0
            return max(1, math.ceil(self.window_seconds - (now - hits[0])))

    def hit(self, key: str) -> None:
        with self._lock:
            now = self._clock()
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)
