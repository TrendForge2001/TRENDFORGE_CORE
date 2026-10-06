"""Provider-agnostic enrichment coordinator for TrendForge stock payloads."""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping
from .contracts import EnrichmentResult, StockPayload
from .provider_registry import ProviderRegistry


class StockEnricher:
    FIELDS = ("fundamentals", "corporate_actions", "big_shark", "market_regime", "sector", "risk")
    FUNDAMENTAL_FIELDS = (
        "roce", "roe", "sales_growth", "profit_growth", "eps_growth",
        "debt_equity", "promoter_holding", "pledged",
    )

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

    @staticmethod
    def _mapping(value: Any) -> dict[str, Any] | None:
        if isinstance(value, Mapping):
            return dict(value)
        if is_dataclass(value):
            return asdict(value)
        return None

    @classmethod
    def _merge_fundamentals(cls, payload: dict[str, Any]) -> None:
        """Flatten canonical fundamental fields while preserving provenance.

        A provider may return a nested fundamentals object for enrichment
        provenance. The engine contract expects canonical metrics at the stock
        payload's top level. Stale snapshots are preserved for diagnostics but
        deliberately not flattened into the scoring contract.
        """
        raw = payload.get("fundamentals")
        fundamentals = cls._mapping(raw)
        if fundamentals is None:
            return
        payload["fundamentals"] = fundamentals

        meta = fundamentals.get("_meta")
        meta = dict(meta) if isinstance(meta, Mapping) else {}
        stale = bool(meta.get("stale", False))

        aliases = {"debt_to_equity": "debt_equity"}
        if not stale:
            for source_name, value in fundamentals.items():
                target_name = aliases.get(source_name, source_name)
                if target_name in cls.FUNDAMENTAL_FIELDS and value is not None:
                    payload[target_name] = value

        if meta:
            payload["fundamental_data_quality"] = {
                "provider": meta.get("provider"),
                "as_of": meta.get("as_of"),
                "age_days": meta.get("age_days"),
                "stale": stale,
                "missing": list(meta.get("missing") or []),
                "warnings": list(meta.get("warnings") or []),
                "source_errors": dict(meta.get("source_errors") or {}),
                "statement_first": bool(meta.get("statement_first", False)),
            }

    def merge(self, stock: StockPayload | dict[str, Any], result: EnrichmentResult) -> dict[str, Any]:
        payload = stock.as_dict() if isinstance(stock, StockPayload) else dict(stock)
        payload.update(result.data)
        self._merge_fundamentals(payload)

        warnings = list(result.warnings)
        quality = payload.get("fundamental_data_quality")
        if isinstance(quality, Mapping):
            warnings.extend(
                f"fundamentals:{warning}"
                for warning in (quality.get("warnings") or [])
            )
        payload["enrichment_warnings"] = list(dict.fromkeys(warnings))
        payload["enrichment_failures"] = list(result.failures)
        payload["enrichment_provenance"] = self.registry.describe()
        return payload

    def health(self) -> dict[str, Any]:
        resolved = self.registry.resolve()
        provider_health = {}
        for field, provider in resolved.items():
            health = getattr(provider, "health", None)
            if callable(health):
                try:
                    provider_health[field] = health()
                except Exception as exc:
                    provider_health[field] = {"status": "degraded", "error": str(exc)}
        return {
            "status": "configured" if resolved else "degraded",
            **self.registry.health(),
            "provider_health": provider_health,
            "max_workers": self.max_workers,
        }


__all__ = ["StockEnricher"]
