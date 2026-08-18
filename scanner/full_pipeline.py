"""End-to-end scanner pipeline: provider -> indicators -> engines -> signal."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.engine_orchestrator import EngineOrchestrator
from indicators.indicator_engine import IndicatorEngine


class FullScannerPipeline:
    """Turn provider candle data into one complete TrendForge analysis."""

    def __init__(self, provider: Any, orchestrator: EngineOrchestrator | None = None, indicator_engine: IndicatorEngine | None = None) -> None:
        self.provider = provider
        self.indicators = indicator_engine or IndicatorEngine()
        self.orchestrator = orchestrator or EngineOrchestrator()

    def _prepare(self, symbol: str, candles: pd.DataFrame, capital: float = 0.0, fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(candles, pd.DataFrame) or candles.empty:
            raise ValueError(f"No candle data available for {symbol}")
        frame = self.indicators.calculate(candles.copy())
        latest = self.indicators.latest(frame)
        snapshot = {
            "close": latest.get("close", 0),
            "atr": latest.get("ATR", 0),
            "rsi": latest.get("RSI", 0),
            "adx": latest.get("ADX", 0),
            "rvol": latest.get("RVOL", 0),
            "vwap": latest.get("VWAP", 0),
        }
        stock: dict[str, Any] = {
            "symbol": symbol.upper(),
            "df": frame,
            "data": frame,
            "candles": frame,
            "snapshot": snapshot,
            "capital": float(capital or 0),
        }
        if fundamentals:
            stock.update(fundamentals)
        return stock

    def analyze(self, symbol: str, period: str = "6mo", interval: str = "1d", capital: float = 0.0, fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        candles = self.provider.candles(symbol, period=period, interval=interval)
        stock = self._prepare(symbol, candles, capital=capital, fundamentals=fundamentals)
        return self.orchestrator.evaluate(stock)

    def analyze_many(self, symbols: list[str], period: str = "6mo", interval: str = "1d", capital: float = 0.0) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                results.append(self.analyze(symbol, period=period, interval=interval, capital=capital))
            except Exception as exc:
                results.append({"symbol": symbol.upper(), "passed": False, "score": 0.0, "confidence": 0.0, "signal": None, "error": str(exc)})
        return sorted(results, key=lambda item: float(item.get("score", 0.0)), reverse=True)


__all__ = ["FullScannerPipeline"]
