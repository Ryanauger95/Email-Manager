from __future__ import annotations

import threading
import time
from collections import deque


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter for API calls."""

    def __init__(self, max_requests: int, per_seconds: float):
        self._max_requests = max_requests
        self._per_seconds = per_seconds
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot is available."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._timestamps and self._timestamps[0] <= now - self._per_seconds:
                    self._timestamps.popleft()

                if len(self._timestamps) < self._max_requests:
                    self._timestamps.append(now)
                    return

                wait_time = self._timestamps[0] + self._per_seconds - now

            time.sleep(wait_time)
