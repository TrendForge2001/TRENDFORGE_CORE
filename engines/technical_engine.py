from __future__ import annotations

from typing import Dict, Any
import math
import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from indicators.indicator_engine import IndicatorEngine


class TechnicalEngine(BaseEngine):
    NAME = "Technical Engine"

    # Canonical indicators produced by FullScannerPipeline/IndicatorEngine.
    REQUIRED_INDICATORS = (
        "EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200",
        "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI",
        "RVOL", "VWAP", "CMF", "MFI", "ATR", "ATR_PERCENT", "BB_WIDTH",
        "SUPPORT", "RESISTANCE", "BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND",
    )

    def __init__(self, indicator_engine=None):
        # Retained for backward compatibility/injection tests. The canonical
        # scanner path consumes the already-calculated dataframe and does not
        # recalculate indicators here.
        self.indicators = indicator_engine or IndicatorEngine()

    @staticmethod
    def _num(row, key):
        try:
            value = float(row.get(key))
            return value if math.isfinite(value) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _flag(row, key):
        value = row.get(key, False)
        return False if pd.isna(value) else bool(value)

    @staticmethod
    def _grade(score):
        if score >= 90:
            return "A+"
        if score >= 80:
            return "A"
        if score >= 70:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    def _has_canonical_indicators(self, df: pd.DataFrame) -> bool:
        return all(column in df.columns for column in self.REQUIRED_INDICATORS)

    def evaluate(self, stock: Dict[str, Any]) -> EngineResult:
        df = stock.get("df")
        if not isinstance(df, pd.DataFrame):
            df = stock.get("data")
        if not isinstance(df, pd.DataFrame):
            return EngineResult(self.NAME, False, 0, 0, "D", warnings=["OHLCV DataFrame not supplied."])

        if len(df) < 30:
            return EngineResult(self.NAME, False, 0, 0, "D", warnings=["Minimum 30 candles required."])

        # FullScannerPipeline owns indicator calculation. Do not execute the
        # indicator engine a second time. A direct legacy TechnicalEngine caller
        # must provide the canonical enriched dataframe explicitly.
        if not self._has_canonical_indicators(df):
            missing = [column for column in self.REQUIRED_INDICATORS if column not in df.columns]
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
        warnings = self._warnings(row)
        confidence = self._confidence(row, total)

        return EngineResult(
            engine=self.NAME,
            passed=(total >= 70 and not self._flag(row, "BREAKDOWN")),
            score=total,
            confidence=confidence,
            grade=self._grade(total),
            reasons=reasons,
            warnings=warnings,
            metrics={
                "close": self._num(row, "close"), "EMA_9": self._num(row, "EMA_9"),
                "EMA_20": self._num(row, "EMA_20"), "EMA_50": self._num(row, "EMA_50"),
                "EMA_100": self._num(row, "EMA_100"), "EMA_200": self._num(row, "EMA_200"),
                "RSI": self._num(row, "RSI"), "MACD": self._num(row, "MACD"),
                "MACD_SIGNAL": self._num(row, "MACD_SIGNAL"), "MACD_HIST": self._num(row, "MACD_HIST"),
                "ADX": self._num(row, "ADX"), "+DI": self._num(row, "+DI"), "-DI": self._num(row, "-DI"),
                "RVOL": self._num(row, "RVOL"), "VWAP": self._num(row, "VWAP"),
                "CMF": self._num(row, "CMF"), "MFI": self._num(row, "MFI"),
                "ATR": self._num(row, "ATR"), "ATR_PERCENT": self._num(row, "ATR_PERCENT"),
                "BB_WIDTH": self._num(row, "BB_WIDTH"), "SUPPORT": self._num(row, "SUPPORT"),
                "RESISTANCE": self._num(row, "RESISTANCE"), "BREAKOUT": self._flag(row, "BREAKOUT"),
                "BREAKDOWN": self._flag(row, "BREAKDOWN"), "UPTREND": self._flag(row, "UPTREND"),
                "DOWNTREND": self._flag(row, "DOWNTREND"),
            },
        )

    # Scoring rules intentionally unchanged below this boundary.
