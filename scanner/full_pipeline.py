"""End-to-end scanner pipeline: provider -> engines -> final signal."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.engine_orchestrator import EngineOrchestrator
from scanner.scanner_engine import ScanResult


class FullScannerPipeline:
    """Turn provider candle data into a complete TrendForge analysis."""

    def __init__(self, provider: Any, orchestrator: EngineOrchestrator | None = None) -> None:
        self.provider = provider
        self.orchestrator = orchestrator or EngineOrchestrator()

    def analyze(self, symbol: str, period: str = "6mo", interval: str = "1d") -> dict[str, Any]:
        candles = self.provider.candles(symbol, period=period, interval=interval)
        if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty:
            raise ValueError(f"No candle data available for {symbol}")
        stock = {"symbol": symbol.upper(), "data": candles, "candles": candles}
        return self.orchestrator.evaluate(stock)

    def analyze_many(self, symbols: list[str], period: str = "6mo", interval: str = "1d") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                results.append(self.analyze(symbol, period=period, interval=interval))
            except Exception as exc:
                results.append({"symbol": symbol.upper(), "passed": False, "score": 0.0, "confidence": 0.0, "signal": None, "error": str(exc)})
        return sorted(results, key=lambda item: float(item.get("score", 0.0)), reverse=True)


__all__ = ["FullScannerPipeline"]
