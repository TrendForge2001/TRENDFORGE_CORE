"""Compatibility wrapper around the canonical FullScannerPipeline."""

from __future__ import annotations

from typing import Any

from scanner.full_pipeline import FullScannerPipeline


class ScannerPipeline:
    """Backward-compatible facade; all execution is delegated to FullScannerPipeline."""

    def __init__(self, provider: Any = None, pipeline: FullScannerPipeline | None = None) -> None:
        if pipeline is not None:
            self.pipeline = pipeline
        else:
            if provider is None:
                raise ValueError("A provider or FullScannerPipeline is required")
            self.pipeline = FullScannerPipeline(provider=provider)

    def scan_symbol(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict[str, Any]:
        return self.pipeline.analyze(symbol, period=period, interval=interval)

    def scan_many(self, symbols: list[str], period: str = "6mo", interval: str = "1d") -> dict[str, Any]:
        return self.pipeline.analyze_many(symbols, period=period, interval=interval)

    def top_n(self, symbols: list[str], n: int = 20, period: str = "6mo", interval: str = "1d") -> dict[str, Any]:
        result = self.scan_many(symbols, period=period, interval=interval)
        if isinstance(result, dict) and isinstance(result.get("top_picks"), list):
            result["top_picks"] = result["top_picks"][:n]
        return result


__all__ = ["ScannerPipeline"]
