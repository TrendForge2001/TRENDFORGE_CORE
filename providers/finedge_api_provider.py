"""Opt-in, read-only FinEdge API transport for Indian fundamentals.

Not an execution-ready fundamentals source. FinEdge JSON must be reconciled
with TrendForge's eight-field, period/source-evidence completion contract
before an operator imports verified figures into local SQLite.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from typing import Any, cast

import requests

BASE_URL = "https://data.finedgeapi.com"
MAX_CALLS_PER_MINUTE = 300
DEFAULT_CALLS_PER_MINUTE = 280
JSONPayload = dict[str, Any] | list[Any]
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9._&-]{0,39}$")
_ENDPOINTS = frozenset(
    {
        "stock-symbols",
        "quote",
        "company-profile",
        "ratios",
        "financial-metrics",
        "shareholding-pattern",
        "ownership-current",
        "corporate-actions-all",
        "refreshed-stocks",
    }
)


class FinEdgeError(RuntimeError):
    """Sanitized transport failure; never includes the query-string token."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class SlidingWindowRateLimiter:
    """Thread-safe rolling-window limiter, covering successful and failed calls."""

    def __init__(
        self,
        calls_per_minute: int = MAX_CALLS_PER_MINUTE,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.limit = min(MAX_CALLS_PER_MINUTE, max(1, int(calls_per_minute)))
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._times: deque[float] = deque()
        self._cooldown_until = 0.0

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                while self._times and now - self._times[0] >= 60.0:
                    self._times.popleft()
                wait = max(0.0, self._cooldown_until - now)
                if len(self._times) >= self.limit:
                    wait = max(wait, self._times[0] + 60.0 - now)
                if wait <= 0:
                    self._times.append(now)
                    return
            # Do not prevent health/cooldown updates while a caller waits.
            self._sleep(max(wait, 0.001))

    def restrict_limit(self, cap: int) -> None:
        """All clients sharing a key use the most conservative requested cap."""
        with self._lock:
            self.limit = min(self.limit, max(1, int(cap)))

    def cooldown(self, seconds: float) -> None:
        with self._lock:
            self._cooldown_until = max(
                self._cooldown_until,
                self._clock() + max(1.0, min(300.0, float(seconds))),
            )

    def health(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            return {
                "max_calls_per_minute": self.limit,
                "recent_reserved_calls": sum(
                    1 for value in self._times if now - value < 60.0
                ),
                "cooldown_seconds_remaining": round(
                    max(0.0, self._cooldown_until - now), 3
                ),
                "scope": "one Python process",
            }


_shared_limiters: dict[str, SlidingWindowRateLimiter] = {}
_shared_lock = threading.Lock()


def _limiter_for(key: str, cap: int) -> SlidingWindowRateLimiter:
    # A different requested cap must not create a second quota for the same key.
    with _shared_lock:
        identifier = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if identifier not in _shared_limiters:
            _shared_limiters[identifier] = SlidingWindowRateLimiter(cap)
        else:
            _shared_limiters[identifier].restrict_limit(cap)
        return _shared_limiters[identifier]


class FinEdgeAPIProvider:
    NAME = "FinEdgeAPIProvider"

    def __init__(
        self,
        *,
        api_key: str = "",
        enabled: bool = False,
        calls_per_minute: int = MAX_CALLS_PER_MINUTE,
        session: requests.Session | None = None,
        limiter: SlidingWindowRateLimiter | None = None,
        timeout: float = 15.0,
    ):
        self.api_key = str(api_key).strip()
        self.enabled = bool(enabled)
        self.calls_per_minute = min(MAX_CALLS_PER_MINUTE, max(1, int(calls_per_minute)))
        self.session = session or requests.Session()
        self.limiter = limiter or _limiter_for(self.api_key, self.calls_per_minute)
        self.timeout = max(1.0, min(60.0, float(timeout)))

    @classmethod
    def from_env(cls, **kwargs: Any) -> FinEdgeAPIProvider:
        api_key = os.getenv("FINEDGE_API_KEY", "").strip()
        enabled = os.getenv(
            "FINEDGE_ENABLED", "true" if api_key else "false"
        ).strip().lower() in {"1", "true", "yes", "on"}
        raw_cap = os.getenv(
            "FINEDGE_RATE_LIMIT_PER_MINUTE", str(DEFAULT_CALLS_PER_MINUTE)
        )
        return cls(
            api_key=api_key,
            enabled=enabled,
            calls_per_minute=int(raw_cap),
            **kwargs,
        )

    @staticmethod
    def _symbol(value: str) -> str:
        symbol = str(value).strip().upper()
        if not _SYMBOL.fullmatch(symbol) or ".." in symbol:
            raise ValueError("Invalid NSE/BSE symbol")
        return symbol

    @staticmethod
    def _path(resource: str, symbol: str | None = None) -> str:
        if resource not in _ENDPOINTS:
            raise ValueError("Unsupported FinEdge resource")
        paths = {
            "stock-symbols": "/api/v1/stock-symbols",
            "quote": "/api/v1/quote",
            "company-profile": "/api/v1/company-profile/{symbol}",
            "ratios": "/api/v1/ratios/{symbol}",
            "financial-metrics": "/api/v1/financial-metrics/{symbol}",
            "shareholding-pattern": "/api/v1/shareholdings/pattern/{symbol}",
            "ownership-current": "/api/v1/shareholdings/ownership-current/{symbol}",
            "corporate-actions-all": "/api/v1/corporate-actions/all",
            "refreshed-stocks": "/api/v1/refreshed-stocks",
        }
        template = paths[resource]
        if "{symbol}" in template:
            if not symbol:
                raise ValueError("Symbol is required")
            return template.format(symbol=FinEdgeAPIProvider._symbol(symbol))
        return template

    def fetch(
        self,
        resource: str,
        *,
        symbol: str | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> JSONPayload:
        if not self.enabled or not self.api_key:
            raise FinEdgeError(
                "FinEdge is disabled or not configured; set FINEDGE_ENABLED "
                "and FINEDGE_API_KEY on the server"
            )
        path = self._path(resource, symbol)
        user_params = dict(params or {})
        if "token" in user_params:
            raise ValueError("The FinEdge API token must not be passed as a parameter")
        # Do not log this URL or the request parameters: auth uses query token.
        arguments = {**user_params, "token": self.api_key}
        self.limiter.acquire()
        try:
            response = self.session.get(
                BASE_URL + path,
                params=arguments,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            # Some Requests exceptions contain URLs with embedded credentials.
            raise FinEdgeError("FinEdge transport unavailable") from None
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "60")
            try:
                seconds = float(retry_after)
            except (TypeError, ValueError):
                seconds = 60.0
            self.limiter.cooldown(seconds)
            raise FinEdgeError("FinEdge rate limit reached (HTTP 429)", 429)
        if response.status_code in {301, 302, 303, 307, 308}:
            raise FinEdgeError(
                "FinEdge unexpected redirect rejected", response.status_code
            )
        if response.status_code >= 400:
            raise FinEdgeError(
                f"FinEdge request failed (HTTP {response.status_code})",
                response.status_code,
            )
        try:
            body = response.json()
        except ValueError:
            raise FinEdgeError("FinEdge did not return valid JSON") from None
        if not isinstance(body, (dict, list)):
            raise FinEdgeError("FinEdge returned an unsupported JSON shape")
        payload = cast(JSONPayload, body)
        if isinstance(payload, dict) and (
            payload.get("success") is False
            or payload.get("status") in ("error", "failed")
            or bool(payload.get("error"))
        ):
            raise FinEdgeError("FinEdge returned a provider error")
        return payload

    def ratios(
        self,
        symbol: str,
        *,
        ratio_type: str = "pr",
        statement_type: str = "c",
    ) -> JSONPayload:
        if ratio_type not in {"pr", "le", "li", "ef"}:
            raise ValueError("Unsupported FinEdge ratio family")
        if statement_type not in {"c", "s"}:
            raise ValueError("Unsupported statement type")
        return self.fetch(
            "ratios",
            symbol=symbol,
            params={"ratio_type": ratio_type, "statement_type": statement_type},
        )

    def financial_metrics(
        self,
        symbol: str,
        *,
        ratio_type: str = "gr",
        statement_type: str = "c",
    ) -> JSONPayload:
        if ratio_type not in {"gr", "av", "cu"}:
            raise ValueError("Unsupported FinEdge metric family")
        if statement_type not in {"c", "s"}:
            raise ValueError("Unsupported statement type")
        return self.fetch(
            "financial-metrics",
            symbol=symbol,
            params={"ratio_type": ratio_type, "statement_type": statement_type},
        )

    def shareholding_pattern(
        self, symbol: str, *, period: str = "quarterly"
    ) -> JSONPayload:
        if period not in {"quarterly", "annual"}:
            raise ValueError("Unsupported shareholding period")
        return self.fetch(
            "shareholding-pattern",
            symbol=symbol,
            params={"period": period},
        )

    def health(self) -> dict[str, Any]:
        state = (
            "disabled"
            if not self.enabled
            else "not_configured"
            if not self.api_key
            else "configured_not_probed"
        )
        return {
            "provider": self.NAME,
            "status": state,
            "api_key_configured": bool(self.api_key),
            "enabled": self.enabled,
            "network_probe": False,
            "base_host": "data.finedgeapi.com",
            "rate_limit": self.limiter.health(),
            "read_only": True,
            "execution_eligibility": "never_auto_approved",
        }


__all__ = ["FinEdgeAPIProvider", "FinEdgeError", "SlidingWindowRateLimiter"]
