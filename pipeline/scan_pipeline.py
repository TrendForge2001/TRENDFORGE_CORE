"""Compatibility facade for the canonical TrendForge scanner pipeline."""

from __future__ import annotations

from typing import Any

from scanner.full_pipeline import FullScannerPipeline


class ScanPipeline:
    """Legacy pipeline facade with one canonical scanner execution boundary."""

    def __init__(
        self,
        scanner=None,
        ranking=None,
        dashboard=None,
        universe=None,
        top_picks=None,
        market_data_adapter=None,
        provider=None,
        period: str = "1y",
        interval: str = "1d",
        **_: Any,
    ) -> None:
        self.scanner = scanner
        self.ranking = ranking
        self.dashboard = dashboard
        self.universe = universe
        self.top_picks = top_picks
        self.market_data_adapter = market_data_adapter or provider
        self.period = period
        self.interval = interval

        if isinstance(scanner, FullScannerPipeline):
            self.pipeline = scanner
        elif self.market_data_adapter is not None:
            self.pipeline = FullScannerPipeline(
                provider=self.market_data_adapter,
            )
        else:
            self.pipeline = None

    def _resolve_symbols(self, symbols=None):
        if symbols is not None:
            return list(symbols)
        if self.universe is None:
            raise ValueError("symbols are required when no universe provider is configured")
        method = getattr(self.universe, "symbols", None)
        if callable(method):
            resolved = list(method())
            if resolved:
                return resolved
        return [member.symbol for member in self.universe.load()]

    def run(self, symbols=None, capital=0, top_n=None):
        symbols = self._resolve_symbols(symbols)
        if self.pipeline is None:
            raise ValueError("FullScannerPipeline requires a market-data provider")

        result = self.pipeline.analyze_many(
            symbols,
            period=self.period,
            interval=self.interval,
            capital=capital,
            top_n=top_n if top_n is not None else 20,
        )

        # Preserve the historical result keys without reimplementing execution,
        # validation, ranking, or engine aggregation in this compatibility layer.
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

    def health(self) -> dict[str, Any]:
        if self.pipeline is None:
            return {
                "status": "degraded",
                "pipeline_configured": False,
                "market_data_configured": self.market_data_adapter is not None,
            }
        health = self.pipeline.health()
        return {
            **health,
            "pipeline_configured": True,
        }


__all__ = ["ScanPipeline"]
