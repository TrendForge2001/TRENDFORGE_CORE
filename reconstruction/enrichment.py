"""Provider-agnostic enrichment coordinator for TrendForge stock payloads."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from .contracts import EnrichmentResult, StockPayload
from .provider_registry import ProviderRegistry


class StockEnricher:
    FIELDS = ("fundamentals", "corporate_actions", "big_shark", "market_regime", "sector", "risk")

    def __init__(self, providers: dict[str, Any] | None = None, registry: ProviderRegistry | None = None, max_workers: int = 6):
        self.registry = registry or ProviderRegistry()
        for field, provider in (providers or {}).items():
            if provider is not None:
                self.registry.register(field, provider)
        self.max_workers = max(1, int(max_workers))

    @staticmethod
    def _call(provider: Any, symbol: str, payload: dict[str, Any]) -> Any:
        if callable(provider):
            return provider(symbol, payload)
        if hasattr(provider, "get"):
            try: return provider.get(symbol, payload)
            except TypeError: return provider.get(symbol)
        if hasattr(provider, "fetch"): return provider.fetch(symbol, payload)
        if hasattr(provider, "load"): return provider.load(symbol)
        raise TypeError("Enrichment provider must be callable or implement get/fetch/load")

    def enrich(self, stock: StockPayload | dict[str, Any]) -> EnrichmentResult:
        payload = stock.as_dict() if isinstance(stock, StockPayload) else dict(stock)
        symbol = str(payload.get("symbol", "")).upper()
        data, warnings, failures = {}, [], []
        for field in self.FIELDS:
            if payload.get(field) is not None:
                data[field] = payload[field]; continue
            specs = self.registry.providers(field)
            if not specs:
                warnings.append(f"provider_not_configured:{field}"); continue
            resolved = False
            for spec in specs:
                try:
                    value = self._call(spec.provider, symbol, payload)
                    if value is not None:
                        data[field] = value; resolved = True; break
                except Exception as exc:
                    failures.append(f"{field}:{spec.name}:{exc}")
            if not resolved and not any(x.startswith(f"{field}:") for x in failures):
                warnings.append(f"no_data:{field}")
        return EnrichmentResult(symbol, data, tuple(warnings), tuple(failures))

    def enrich_many(self, stocks: dict[str, StockPayload | dict[str, Any]]) -> dict[str, EnrichmentResult]:
        if not stocks: return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(stocks)), thread_name_prefix="trendforge-enrich") as executor:
            futures = {executor.submit(self.enrich, stock): symbol for symbol, stock in stocks.items()}
            for future in as_completed(futures):
                symbol = futures[future]
                try: results[symbol] = future.result()
                except Exception as exc: results[symbol] = EnrichmentResult(symbol, failures=(str(exc),))
        return results

    def merge(self, stock: StockPayload | dict[str, Any], result: EnrichmentResult) -> dict[str, Any]:
        payload = stock.as_dict() if isinstance(stock, StockPayload) else dict(stock)
        payload.update(result.data)
        payload["enrichment_warnings"] = list(result.warnings)
        payload["enrichment_failures"] = list(result.failures)
        payload["enrichment_provenance"] = self.registry.describe()
        return payload

    def health(self) -> dict[str, Any]:
        return {"status": "configured" if self.registry.resolve() else "degraded", **self.registry.health(), "max_workers": self.max_workers}


__all__ = ["StockEnricher"]
