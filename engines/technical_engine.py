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


    def _trend_score(self, row, previous):
        score, reasons = 0.0, []
        close = self._num(row, "close") or 0.0
        for key, points in (("EMA_9", 6), ("EMA_20", 6), ("EMA_50", 6), ("EMA_200", 6)):
            value = self._num(row, key)
            if value is not None and close > value:
                score += points
        if self._flag(row, "UPTREND"): score += 6
        return min(30.0, score), reasons

    def _momentum_score(self, row, previous):
        score, reasons = 0.0, []
        rsi = self._num(row, "RSI")
        macd = self._num(row, "MACD")
        signal = self._num(row, "MACD_SIGNAL")
        if rsi is not None and 50 <= rsi <= 70: score += 10
        if macd is not None and signal is not None and macd > signal: score += 10
        return min(25.0, score), reasons

    def _volume_score(self, row, previous):
        score, reasons = 0.0, []
        rvol = self._num(row, "RVOL")
        if rvol is not None:
            if rvol >= 2: score = 20
            elif rvol >= 1.5: score = 15
            elif rvol >= 1: score = 10
        return score, reasons

    def _price_action_score(self, row):
        score, reasons = 0.0, []
        if self._flag(row, "BREAKOUT"): score += 15
        if self._flag(row, "UPTREND"): score += 5
        if self._flag(row, "BREAKDOWN"): score = 0
        return min(15.0, score), reasons

    def _volatility_score(self, row):
        score, reasons = 0.0, []
        atrp = self._num(row, "ATR_PERCENT")
        if atrp is not None and 1 <= atrp <= 5: score = 10
        elif atrp is not None and atrp < 10: score = 5
        return score, reasons


    def _confidence(self, row, score):
        available = sum(self._num(row, key) is not None for key in
                        ("EMA_20", "EMA_50", "EMA_200", "RSI", "ADX", "ATR_PERCENT", "RVOL"))
        return round(max(0.0, min(100.0, float(score) * (0.7 + 0.3 * available / 7.0))), 2)

    def _warnings(self, row):
        warnings = []
        if self._flag(row, "BREAKDOWN"):
            warnings.append("Price breakdown detected.")
        return warnings
