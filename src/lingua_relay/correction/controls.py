from __future__ import annotations

import threading
import time
from dataclasses import dataclass


class RateLimiter:
    """Thread-safe token bucket with a one-minute refill window."""

    def __init__(self, requests_per_minute: int, *, clock=time.monotonic) -> None:
        if requests_per_minute < 1:
            raise ValueError("requests_per_minute must be positive")
        self._capacity = float(requests_per_minute)
        self._tokens = float(requests_per_minute)
        self._rate = requests_per_minute / 60.0
        self._clock = clock
        self._updated = clock()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = self._clock()
            elapsed = max(0.0, now - self._updated)
            self._updated = now
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    state: str
    consecutive_failures: int
    retry_after_seconds: float


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        recovery_seconds: float,
        *,
        clock=time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("invalid circuit-breaker settings")
        self._threshold = failure_threshold
        self._recovery = recovery_seconds
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self._recovery or self._probe_in_flight:
                return False
            self._probe_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._probe_in_flight = False
            self._failures += 1
            if self._failures >= self._threshold:
                self._opened_at = self._clock()

    def snapshot(self) -> CircuitSnapshot:
        with self._lock:
            if self._opened_at is None:
                state = "closed"
                retry_after = 0.0
            else:
                elapsed = self._clock() - self._opened_at
                retry_after = max(0.0, self._recovery - elapsed)
                state = "half_open" if retry_after == 0 else "open"
            return CircuitSnapshot(state, self._failures, retry_after)
