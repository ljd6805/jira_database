from __future__ import annotations

import threading
import time
from collections.abc import Callable


class IntervalRateLimiter:
    """Thread-safe minimum-interval limiter.

    The collector uses a single worker, but the lock prevents accidental future
    parallel callers from bypassing the configured request interval.
    """

    def __init__(
        self,
        requests_per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be positive")
        self._interval = 60.0 / requests_per_minute
        self._clock = clock
        self._sleeper = sleeper
        self._lock = threading.Lock()
        self._last_request_started_at: float | None = None

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if self._last_request_started_at is not None:
                elapsed = now - self._last_request_started_at
                remaining = self._interval - elapsed
                if remaining > 0:
                    self._sleeper(remaining)
                    now = self._clock()
            self._last_request_started_at = now
