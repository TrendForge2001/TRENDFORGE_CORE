"""Backend-owned, cached FinEdge fundamental observations.

Keep source payloads intact until units, fiscal periods and account schema have
been verified. Transport success alone does not establish scanner eligibility.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import os
import threading
import time
from typing import Any, Callable

from providers.finedge_api_provider import FinEdgeAPIProvider


def collect_fundamental_observations(
    provider: FinEdgeAPIProvider, symbols: list[str], *, statement_type: str = "c",
) -> dict[str, Any]:
    if len(symbols) > 25 or not symbols:
        raise ValueError("Batch must contain 1 to 25 symbols")
    if statement_type not in {"c", "s"}:
        raise ValueError("Invalid statement type")
    rows = []
    for symbol in symbols:
        # 4 requests per symbol; the shared limiter includes failed calls.
        # Do not suppress 401/429/503 into zero-valued financial indicators.
        rows.append({
            "symbol": FinEdgeAPIProvider._symbol(symbol),
            "source": "FINEDGE_API",
            "source_url": "https://www.finedgeapi.com/",
            "statement_type": statement_type,
            "verified_for_scanner": False,
            "profitability_ratios": provider.ratios(
                symbol, ratio_type="pr", statement_type=statement_type
            ),
            "leverage_ratios": provider.ratios(
                symbol, ratio_type="le", statement_type=statement_type
            ),
            "growth_metrics": provider.financial_metrics(
                symbol, ratio_type="gr", statement_type=statement_type
            ),
            "shareholding_quarterly": provider.shareholding_pattern(
                symbol, period="quarterly"
            ),
        })
    return {
        "schema_version": "R71.2-candidates-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "field_contract": "raw external observations; not validated as scanner ready",
        "symbols": rows,
        "provider": provider.NAME,
        "api_calls": 4 * len(rows),
    }



class FinEdgeFundamentalService:
    def __init__(
        self, provider: FinEdgeAPIProvider | None = None, *,
        cache_ttl_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.provider = provider if provider is not None else FinEdgeAPIProvider.from_env()
        ttl = cache_ttl_seconds if cache_ttl_seconds is not None else float(
            os.getenv("FINEDGE_CACHE_TTL_SECONDS", "21600")
        )
        self.cache_ttl = max(0.0, min(86400.0, float(ttl)))
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, str], tuple[float, dict[str, Any]]] = OrderedDict()

    def health(self) -> dict[str, Any]:
        # A readiness read never performs a provider request or waits for fetching.
        return {
            **self.provider.health(),
            "cache_ttl_seconds": self.cache_ttl,
            "requests_per_uncached_symbol": 4,
            "credential_location": "backend_environment",
            "automatic_database_writes": False,
        }

    def fetch(
        self, symbol: str, *, statement_type: str = "c", force_refresh: bool = False,
    ) -> dict[str, Any]:
        normalized = FinEdgeAPIProvider._symbol(symbol)
        if statement_type not in {"c", "s"}:
            raise ValueError("Invalid financial statement type")
        key = (normalized, statement_type)
        # Serialize session access and coalesce concurrent cache misses. This
        # service is shared by the backend factory, not reconstructed per page.
        with self._lock:
            cached = self._cache.get(key)
            if cached and not force_refresh and self._clock() - cached[0] < self.cache_ttl:
                self._cache.move_to_end(key)
                result = deepcopy(cached[1])
                result["cache"] = {
                    "hit": True, "age_seconds": round(self._clock() - cached[0], 3),
                    "ttl_seconds": self.cache_ttl,
                }
                result["api_calls"] = 0
                return result

            result = collect_fundamental_observations(self.provider, [normalized], statement_type=statement_type)
            # Never cache a failed/partial fetch as a successful fundamental report.
            result["source_api_calls"] = result["api_calls"]
            result["cache"] = {"hit": False, "age_seconds": 0, "ttl_seconds": self.cache_ttl}
            self._cache[key] = (self._clock(), deepcopy(result))
            self._cache.move_to_end(key)
            while len(self._cache) > 512:
                self._cache.popitem(last=False)
            return result

    def close(self) -> None:
        with self._lock:
            self._cache.clear()
            close = getattr(getattr(self.provider, "session", None), "close", None)
            if callable(close):
                close()
