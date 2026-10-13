"""Thread-safe provider circuit breaker used by market-data routing."""
from __future__ import annotations

import threading
import time
from typing import Any


class ProviderCircuitOpenError(RuntimeError):
    """Raised when an upstream provider is in an active cooldown."""


class ProviderCircuitBreaker:
    """Consecutive systemic-failure breaker with timed recovery."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 2,
        cooldown_seconds: float = 120.0,
    ) -> None:
        self.name = str(name or "provider")
        self.failure_threshold = max(1, int(failure_threshold))
        self.cooldown_seconds = max(1.0, float(cooldown_seconds))
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_until = 0.0
        self._last_error: str | None = None
        self._last_failure_at: float | None = None
        self._last_success_at: float | None = None
        self._open_count = 0

    def _remaining_unlocked(self, now: float) -> int:
        return max(0, int(round(self._opened_until - now)))

    def allow_request(self) -> bool:
        now = time.time()
        with self._lock:
            if self._opened_until <= now:
                if self._opened_until > 0:
                    self._opened_until = 0.0
                    self._consecutive_failures = 0
                return True
            return False

    def require_request_allowed(self) -> None:
        if self.allow_request():
            return
        health = self.health()
        raise ProviderCircuitOpenError(
            f"{self.name} circuit open; retry in "
            f"{health['retry_after_seconds']}s"
        )

    def record_success(self) -> None:
        now = time.time()
        with self._lock:
            self._consecutive_failures = 0
            self._opened_until = 0.0
            self._last_error = None
            self._last_success_at = now

    def record_failure(self, error: Exception | str) -> bool:
        now = time.time()
        text = str(error)
        opened = False
        with self._lock:
            self._consecutive_failures += 1
            self._last_error = text
            self._last_failure_at = now
            if self._consecutive_failures >= self.failure_threshold:
                self._opened_until = max(
                    self._opened_until,
                    now + self.cooldown_seconds,
                )
                self._open_count += 1
                opened = True
        return opened

    def health(self) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            retry_after = self._remaining_unlocked(now)
            state = "open" if retry_after > 0 else "closed"
            return {
                "name": self.name,
                "state": state,
                "failure_threshold": self.failure_threshold,
                "cooldown_seconds": self.cooldown_seconds,
                "consecutive_failures": self._consecutive_failures,
                "retry_after_seconds": retry_after,
                "last_error": self._last_error,
                "last_failure_at_epoch": self._last_failure_at,
                "last_success_at_epoch": self._last_success_at,
                "open_count": self._open_count,
            }


__all__ = [
    "ProviderCircuitBreaker",
    "ProviderCircuitOpenError",
]
