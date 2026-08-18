"""Provider-agnostic enrichment coordinator for TrendForge stock payloads."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .contracts import EnrichmentResult, StockPayload


class StockEnricher:
    """Populate optional engine inputs without coupling engines to providers."""

    FIELDS = (
        "fundamentals",
        "corporate_actions",
        "big_shark",
        "market_regime",
        "sector",
        "risk",
    )

    def __init__(self, providers: dict[str, Any] | None = None, max_workers: int = 6):
        self.providers = providers or {}
        self.max_workers = max(1, int(max_workers))

    @staticmethod
    def _call(provider: Any, symbol: str, payload: dict[str, Any]) -> Any:
        if callable(provider):
            return provider(symbol, payload)
        if hasattr(provider, "get"):
            try:
                return provider.get(symbol, payload)
            except TypeError:
                return provider.get(symbol)
        if hasattr(provider, "fetch"):
            return provider.fetch(symbol, payload)
        if hasattr(provider, "load"):
            return provider.load(symbol)
        raise TypeError("Enrichment provider must be callable or implement get/fetch/load")

    def enrich(self, stock: StockPayload | dict[str, Any]) -> EnrichmentResult:
        payload = stock.as_dict() if isinstance(stock, StockPayload) else dict(stock)
        symbol = str(payload.get("symbol", "")).upper()
        data: dict[str, Any] = {}
        warnings: list[str] = []
        failures: list[str] = []

        for field in self.FIELDS:
            if payload.get(field) is not None:
                data[field] = payload[field]
                continue
            provider = self.providers.get(field)
            if provider is None:
                warnings.append(f"provider_not_configured:{field}")
                continue
            try:
                value = self._call(provider, symbol, payload)
                if value is None:
                    warnings.append(f"no_data:{field}")
                else:
                    data[field] = value
            except Exception as exc:
                failures.append(f"{field}:{exc}")

        return EnrichmentResult(symbol, data, tuple(warnings), tuple(failures))

    def enrich_many(self, stocks: dict[str, StockPayload | dict[str, Any]]) -> dict[str, EnrichmentResult]:
        if not stocks:
            return {}
        workers = min(self.max_workers, len(stocks))
        results: dict[str, EnrichmentResult] = {}
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trendforge-enrich") as executor:
            futures = {executor.submit(self.enrich, stock): symbol for symbol, stock in stocks.items()}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    results[symbol] = EnrichmentResult(symbol, failures=(str(exc),))
        return results

    def merge(self, stock: StockPayload | dict[str, Any], result: EnrichmentResult) -> dict[str, Any]:
        payload = stock.as_dict() if isinstance(stock, StockPayload) else dict(stock)
        payload.update(result.data)
        payload.setdefault("enrichment_warnings", list(result.warnings))
        payload.setdefault("enrichment_failures", list(result.failures))
        return payload

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.providers else "degraded",
            "configured_fields": sorted(self.providers),
            "missing_fields": [field for field in self.FIELDS if field not in self.providers],
            "max_workers": self.max_workers,
        }


__all__ = ["StockEnricher"]
