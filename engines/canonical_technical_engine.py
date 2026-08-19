from __future__ import annotations

from typing import Any
import math
import pandas as pd

from engines.base_engine import EngineResult
from engines.technical_engine import TechnicalEngine


class CanonicalTechnicalEngine(TechnicalEngine):
    """Technical scoring facade that consumes the pipeline's indicator frame.

    FullScannerPipeline owns the single IndicatorEngine calculation. This class
    preserves TechnicalEngine's scoring methods while preventing a second
    indicator calculation on the canonical execution path.
    """

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        df = stock.get("df")
        if not isinstance(df, pd.DataFrame):
            df = stock.get("data")
        if not isinstance(df, pd.DataFrame):
            return EngineResult(self.NAME, False, 0, 0, "D", warnings=["OHLCV DataFrame not supplied."])
        if len(df) < 30:
            return EngineResult(self.NAME, False, 0, 0, "D", warnings=["Minimum 30 candles required."])

        required = getattr(self, "REQUIRED_INDICATORS", ())
        missing = [column for column in required if column not in df.columns]
        if missing:
            return EngineResult(
                self.NAME, False, 0, 0, "D",
                warnings=["Canonical indicator dataframe required.", "Missing indicators: " + ", ".join(missing)],
            )

        row = df.iloc[-1]
        previous = df.iloc[-2]
        trend_score, trend_reasons = self._trend_score(row, previous)
        momentum_score, momentum_reasons = self._momentum_score(row, previous)
        volume_score, volume_reasons = self._volume_score(row, previous)
        price_score, price_reasons = self._price_action_score(row)
        volatility_score, volatility_reasons = self._volatility_score(row)
        total = round(trend_score + momentum_score + volume_score + price_score + volatility_score, 2)
        reasons = trend_reasons + momentum_reasons + volume_reasons + price_reasons + volatility_reasons

        return EngineResult(
            engine=self.NAME,
            passed=(total >= 70 and not self._flag(row, "BREAKDOWN")),
            score=total,
            confidence=self._confidence(row, total),
            grade=self._grade(total),
            reasons=reasons,
            warnings=self._warnings(row),
            metrics={
                key: (self._flag(row, key) if key in {"BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND"} else self._num(row, key))
                for key in (
                    "close", "EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200",
                    "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI",
                    "RVOL", "VWAP", "CMF", "MFI", "ATR", "ATR_PERCENT", "BB_WIDTH",
                    "SUPPORT", "RESISTANCE", "BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND",
                )
            },
        )


__all__ = ["CanonicalTechnicalEngine"]
