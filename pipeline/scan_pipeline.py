"""Canonical end-to-end TrendForge scanner pipeline."""

from __future__ import annotations
from typing import Any
from providers.market_data_adapter import MarketDataAdapter
from reconstruction.contracts import StockPayload
from reconstruction.enrichment import StockEnricher
from reconstruction.input_normalizer import EngineInputNormalizer
from reconstruction.provider_bootstrap import build_provider_registry
from universe.data_validation import MarketDataValidator


class ScanPipeline:
    """Run universe -> data -> validation -> enrichment -> normalization -> engines -> ranking."""
    def __init__(self, scanner, ranking, dashboard, universe=None, top_picks=None,
                 data_validator: MarketDataValidator | None = None, data_loader=None,
                 market_data_adapter: MarketDataAdapter | None = None,
                 enricher: StockEnricher | None = None, provider_registry=None,
                 provider_bootstrap_kwargs: dict[str, Any] | None = None,
                 data_period: str = "1y", data_interval: str = "1d"):
        self.scanner, self.ranking, self.dashboard = scanner, ranking, dashboard
        self.universe, self.top_picks = universe, top_picks
        self.data_validator, self.data_loader = data_validator, data_loader
        self.market_data_adapter = market_data_adapter
        self.provider_registry = provider_registry
        self.provider_bootstrap_kwargs = provider_bootstrap_kwargs or {}
        self.enricher = enricher or self._build_enricher()
        self.normalizer = EngineInputNormalizer()
        self.data_period, self.data_interval = data_period, data_interval

    def _build_enricher(self):
        if self.provider_registry is not None:
            return StockEnricher(registry=self.provider_registry)
        if self.provider_bootstrap_kwargs:
            registry = build_provider_registry(**self.provider_bootstrap_kwargs)
            self.provider_registry = registry
            return StockEnricher(registry=registry)
        return None

    def _resolve_symbols(self, symbols):
        if symbols is not None: return list(symbols)
        if self.universe is None: raise ValueError("symbols are required when no universe provider is configured")
        method = getattr(self.universe, "symbols", None)
        if callable(method):
            resolved = list(method())
            if resolved: return resolved
        return [member.symbol for member in self.universe.load()]

    def _load_frames(self, symbols):
        if self.market_data_adapter is not None and self.data_loader is None:
            frames = self.market_data_adapter.batch_candles(symbols, period=self.data_period, interval=self.data_interval)
            missing = set(symbols) - set(frames)
            return frames, [{"symbol": s, "valid": False, "reasons": ["market_data_fetch_failed"]} for s in sorted(missing)]
        frames, rejected = {}, []
        for symbol in symbols:
            try:
                frame = self.data_loader(symbol) if self.data_loader is not None else None
                if frame is None: rejected.append({"symbol": symbol, "valid": False, "reasons": ["market_data_not_configured"]})
                else: frames[symbol] = frame
            except Exception as exc: rejected.append({"symbol": symbol, "valid": False, "reasons": [f"data_loader_error:{exc}"]})
        return frames, rejected

    def _validate_data(self, symbols):
        frames, rejected = self._load_frames(symbols)
        if self.data_validator is None: return list(frames), rejected, frames
        valid, validation_rejected = self.data_validator.validate_many(frames)
        rejected.extend(item.as_dict() for item in validation_rejected)
        return valid, rejected, {s: frames[s] for s in valid}

    def _build_payloads(self, frames):
        return {s: StockPayload(symbol=s, df=f) for s, f in frames.items()}

    def _enrich(self, payloads):
        if self.enricher is None or not payloads: return {s: p.as_dict() for s, p in payloads.items()}, []
        results = self.enricher.enrich_many(payloads)
        enriched, warnings = {}, []
        for symbol, payload in payloads.items():
            result = results.get(symbol)
            if result is None:
                enriched[symbol] = payload.as_dict(); warnings.append({"symbol": symbol, "reasons": ["enrichment_result_missing"]}); continue
            enriched[symbol] = self.enricher.merge(payload, result)
            if result.warnings or result.failures: warnings.append({"symbol": symbol, "warnings": list(result.warnings), "failures": list(result.failures)})
        return enriched, warnings

    def _scan_valid_payloads(self, payloads, capital=0):
        normalized = self.normalizer.normalize_many(payloads)
        if hasattr(self.scanner, "scan_payload_many"): return self.scanner.scan_payload_many(normalized, capital=capital)
        results = []
        for symbol, payload in normalized.items():
            try: results.append(self.scanner.scan(symbol, payload["df"], metadata=payload))
            except Exception: continue
        return results

    def run(self, symbols=None, capital=0, top_n=None):
        resolved = self._resolve_symbols(symbols)
        valid, rejected, frames = self._validate_data(resolved)
        payloads, enrichment_warnings = self._enrich(self._build_payloads(frames))
        rejected.extend(enrichment_warnings)
        signals = self._scan_valid_payloads(payloads, capital)
        ranked = self.ranking.rank(signals)
        limit = top_n if top_n is not None else 20
        picks = self.top_picks.get(ranked, limit=limit) if self.top_picks is not None else ranked[:limit]
        return {"ranked": ranked, "top_picks": picks, "summary": self.dashboard.build(ranked), "universe_size": len(resolved), "validated_size": len(valid), "rejected": rejected, "rejected_count": len(rejected), "market_data_loaded": len(frames), "enriched_count": len(payloads), "analyzed_count": len(signals)}

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "universe_configured": self.universe is not None, "data_validation_configured": self.data_validator is not None, "market_data_configured": self.market_data_adapter is not None or self.data_loader is not None, "enrichment_configured": self.enricher is not None, "provider_registry_configured": self.provider_registry is not None, "normalizer_configured": True, "top_picks_configured": self.top_picks is not None, "data_period": self.data_period, "data_interval": self.data_interval}
