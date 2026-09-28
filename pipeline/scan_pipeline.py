"""Compatibility facade for the canonical TrendForge scanner pipeline."""
from __future__ import annotations

from typing import Any

from scanner.full_pipeline import FullScannerPipeline


class ScanPipeline:
    def __init__(self, scanner=None, ranking=None, dashboard=None, universe=None,
                 top_picks=None, market_data_adapter=None, provider=None,
                 period="1y", interval="1d", **kwargs: Any):
        self.scanner = scanner
        self.ranking = ranking
        self.dashboard = dashboard
        self.universe = universe
        self.top_picks = top_picks
        self.market_data_adapter = market_data_adapter or provider
        self.period = period
        self.interval = interval
        self.pipeline = scanner if isinstance(scanner, FullScannerPipeline) else None
        if self.pipeline is None and self.market_data_adapter is not None:
            self.pipeline = FullScannerPipeline(self.market_data_adapter)

    def _resolve_symbols(self, symbols=None):
        if symbols is not None:
            return list(symbols)
        if self.universe is None:
            raise ValueError("symbols are required when no universe provider is configured")
        method = getattr(self.universe, "symbols", None)
        if callable(method):
            return list(method())
        return [member.symbol for member in self.universe.load()]

    def run(self, symbols=None, capital=0, top_n=None):
        symbols = self._resolve_symbols(symbols)
        if self.pipeline is None:
            raise ValueError("FullScannerPipeline requires a market-data provider")
        result = self.pipeline.analyze_many(
            symbols, period=self.period, interval=self.interval,
            capital=capital, top_n=top_n if top_n is not None else 20,
        )
        return {
            **result,
            "ranked": result.get("results", []),
            "summary": result.get("summary", {}),
            "universe_size": len(symbols),
            "validated_size": result.get("scanned_count", 0),
            "market_data_loaded": result.get("scanned_count", 0),
            "enriched_count": result.get("scanned_count", 0),
            "analyzed_count": result.get("count", 0),
        }

    def health(self):
        if self.pipeline is None:
            return {"status": "degraded", "pipeline_configured": False,
                    "market_data_configured": self.market_data_adapter is not None}
        return {**self.pipeline.health(), "pipeline_configured": True}


__all__ = ["ScanPipeline"]
