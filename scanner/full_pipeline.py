"""End-to-end canonical TrendForge scanner pipeline."""

from __future__ import annotations

from typing import Any

import pandas as pd

from engines.engine_orchestrator import EngineOrchestrator
from indicators.indicator_engine import IndicatorEngine


class FullScannerPipeline:
    """Provider -> indicators -> engines -> gates -> ranking -> top picks."""

    def __init__(
        self,
        provider: Any,
        orchestrator: EngineOrchestrator | None = None,
        indicator_engine: IndicatorEngine | None = None,
    ) -> None:
        self.provider = provider
        self.indicators = indicator_engine or IndicatorEngine()
        self.orchestrator = orchestrator or EngineOrchestrator()

    def _prepare(
        self,
        symbol: str,
        candles: pd.DataFrame,
        capital: float = 0.0,
        fundamentals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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

    @staticmethod
    def _signal_name(signal: Any) -> str:
        return str(getattr(signal, "signal", signal or "HOLD")).upper()

    @staticmethod
    def _is_eligible(result: dict[str, Any]) -> bool:
        if not result.get("passed", False):
            return False
        signal = result.get("signal")
        name = FullScannerPipeline._signal_name(signal)
        if name in {"SELL", "REDUCE", "IGNORE", "ERROR"}:
            return False
        if any(
            engine.get("metrics", {}).get("hard_block") is True
            for engine in result.get("engines", {}).values()
        ):
            return False
        return True

    @staticmethod
    def _rank_key(result: dict[str, Any]) -> tuple[float, float]:
        return (
            float(result.get("score", 0.0) or 0.0),
            float(result.get("confidence", 0.0) or 0.0),
        )

    def _finalize(self, results: list[dict[str, Any]], top_n: int = 20) -> dict[str, Any]:
        eligible = [item for item in results if self._is_eligible(item)]
        rejected = [item for item in results if item not in eligible]
        ranked = sorted(eligible, key=self._rank_key, reverse=True)
        return {
            "results": ranked,
            "eligible": ranked,
            "rejected": rejected,
            "top_picks": ranked[: max(0, int(top_n))],
            "count": len(ranked),
            "rejected_count": len(rejected),
        }

    def analyze(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        fundamentals: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        candles = self.provider.candles(symbol, period=period, interval=interval)
        stock = self._prepare(symbol, candles, capital=capital, fundamentals=fundamentals)
        result = self.orchestrator.evaluate(stock)
        result["symbol"] = symbol.upper()
        result["eligible"] = self._is_eligible(result)
        return result

    def analyze_many(
        self,
        symbols: list[str],
        period: str = "6mo",
        interval: str = "1d",
        capital: float = 0.0,
        top_n: int = 20,
    ) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                results.append(
                    self.analyze(
                        symbol,
                        period=period,
                        interval=interval,
                        capital=capital,
                    )
                )
            except Exception as exc:
                results.append(
                    {
                        "symbol": symbol.upper(),
                        "passed": False,
                        "score": 0.0,
                        "confidence": 0.0,
                        "signal": "ERROR",
                        "eligible": False,
                        "error": str(exc),
                    }
                )
        return self._finalize(results, top_n=top_n)


__all__ = ["FullScannerPipeline"]
