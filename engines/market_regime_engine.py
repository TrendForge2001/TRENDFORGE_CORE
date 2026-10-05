"""
TrendForge v2
Market Regime Engine

Purpose:
    Determine the broader market environment before allowing
    intraday / short-swing signals.

Regimes:
    BULLISH
    BEARISH
    SIDEWAYS
    HIGH_VOLATILITY
    RISK_OFF

The engine is a FILTER, not a trade generator.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from indicators.indicator_engine import IndicatorEngine


class MarketRegimeEngine(BaseEngine):

    NAME = "Market Regime Engine"

    def __init__(
        self,
        indicator_engine: IndicatorEngine | None = None,
    ):

        self.indicators = (
            indicator_engine
            or IndicatorEngine()
        )

    # =========================================================
    # HELPERS
    # =========================================================

    @staticmethod
    def _num(
        row: pd.Series,
        *keys: str,
    ) -> float | None:

        for key in keys:

            try:

                value = row.get(key)

                if value is None or pd.isna(value):
                    continue

                value = float(value)

                if math.isfinite(value):
                    return value

            except (
                TypeError,
                ValueError,
            ):
                continue

        return None

    @staticmethod
    def _flag(
        row: pd.Series,
        *keys: str,
    ) -> bool:

        for key in keys:

            try:

                value = row.get(
                    key,
                    False,
                )

                if (
                    value is not None
                    and not pd.isna(value)
                    and bool(value)
                ):

                    return True

            except (
                TypeError,
                ValueError,
            ):
                continue

        return False

    @staticmethod
    def _grade(
        score: float,
    ) -> str:

        if score >= 90:
            return "A+"

        if score >= 80:
            return "A"

        if score >= 70:
            return "B"

        if score >= 60:
            return "C"

        return "D"

    @staticmethod
    def _frame(
        stock: Dict[str, Any],
    ) -> pd.DataFrame | None:

        for key in (
            "df",
            "data",
            "ohlcv",
            "candles",
            "history",
        ):

            value = stock.get(key)

            if isinstance(
                value,
                pd.DataFrame,
            ):

                return value.copy()

        return None

    # =========================================================
    # MAIN
    # =========================================================

    def evaluate(
        self,
        stock: Dict[str, Any],
    ) -> EngineResult:

        df = self._frame(
            stock
        )

        if df is None:

            return EngineResult(

                engine=self.NAME,

                passed=False,

                score=0.0,

                confidence=0.0,

                grade="D",

                warnings=[
                    "Market OHLCV data not supplied."
                ],

            )

        if len(df) < 50:

            return EngineResult(

                engine=self.NAME,

                passed=False,

                score=0.0,

                confidence=0.0,

                grade="D",

                warnings=[
                    "Minimum 50 candles required."
                ],

            )

        # IndicatorEngine is owned by FullScannerPipeline.
        # This engine consumes the already-enriched dataframe.
        row = df.iloc[-1]

        previous = df.iloc[-2]

        trend_score, trend_reasons = (
            self._trend_score(
                row,
            )
        )

        momentum_score, momentum_reasons = (
            self._momentum_score(
                row,
                previous,
            )
        )

        volatility_score, volatility_reasons = (
            self._volatility_score(
                row,
            )
        )

        participation_score, participation_reasons = (
            self._participation_score(
                row,
            )
        )

        breadth_score, breadth_reasons = (
            self._breadth_score(
                stock,
            )
        )

        raw_score = (
            trend_score
            + momentum_score
            + volatility_score
            + participation_score
            + breadth_score
        )

        score = round(
            max(
                0.0,
                min(
                    100.0,
                    raw_score,
                ),
            ),
            2,
        )

        regime = self._regime(
            row,
            score,
        )

        direction = self._direction(
            row,
        )

        warnings = self._warnings(
            row,
            regime,
        )

        reasons = (
            trend_reasons
            + momentum_reasons
            + volatility_reasons
            + participation_reasons
            + breadth_reasons
        )

        confidence = self._confidence(
            row,
            score,
        )

        passed = regime not in (
            "RISK_OFF",
        )

        return EngineResult(

            engine=self.NAME,

            passed=passed,

            score=score,

            confidence=confidence,

            grade=self._grade(
                score
            ),

            reasons=reasons[:25],

            warnings=warnings,

            metrics={

                "regime": regime,

                "direction": direction,

                "score": score,

                "trend_score": trend_score,

                "momentum_score": momentum_score,

                "volatility_score": volatility_score,

                "participation_score":
                    participation_score,

                "breadth_score":
                    breadth_score,

                "close": self._num(
                    row,
                    "close",
                    "Close",
                ),

                "EMA_20": self._num(
                    row,
                    "EMA_20",
                    "ema_20",
                ),

                "EMA_50": self._num(
                    row,
                    "EMA_50",
                    "ema_50",
                ),

                "EMA_200": self._num(
                    row,
                    "EMA_200",
                    "ema_200",
                ),

                "RSI": self._num(
                    row,
                    "RSI",
                    "rsi",
                ),

                "ADX": self._num(
                    row,
                    "ADX",
                    "adx",
                ),

                "ATR_PERCENT": self._num(
                    row,
                    "ATR_PERCENT",
                    "atr_percent",
                ),

                "RVOL": self._num(
                    row,
                    "RVOL",
                    "rvol",
                ),

            },

        )

    # =========================================================
    # TREND — 30
    # =========================================================

    def _trend_score(
        self,
        row,
    ):

        score = 0.0

        reasons = []

        close = self._num(
            row,
            "close",
            "Close",
        )

        ema20 = self._num(
            row,
            "EMA_20",
            "ema_20",
        )

        ema50 = self._num(
            row,
            "EMA_50",
            "ema_50",
        )

        ema200 = self._num(
            row,
            "EMA_200",
            "ema_200",
        )

        if all(
            x is not None
            for x in (
                close,
                ema20,
                ema50,
                ema200,
            )
        ):

            if (
                close > ema20
                > ema50
                > ema200
            ):

                score += 30

                reasons.append(
                    "Strong bullish market structure"
                )

            elif (
                close > ema50
                > ema200
            ):

                score += 22

                reasons.append(
                    "Bullish medium/long-term structure"
                )

            elif (
                close > ema200
            ):

                score += 15

            elif (
                close < ema20
                < ema50
                < ema200
            ):

                reasons.append(
                    "Strong bearish market structure"
                )

            elif (
                close < ema50
                < ema200
            ):

                score += 3

                reasons.append(
                    "Bearish medium/long-term structure"
                )

            else:

                score += 8

                reasons.append(
                    "Mixed market trend"
                )

        if self._flag(
            row,
            "UPTREND",
            "uptrend",
        ):

            score += 5

        if self._flag(
            row,
            "DOWNTREND",
            "downtrend",
        ):

            score = max(
                0,
                score - 8,
            )

        return (
            min(
                30,
                score,
            ),
            reasons,
        )

    # =========================================================
    # MOMENTUM — 20
    # =========================================================

    def _momentum_score(
        self,
        row,
        previous,
    ):

        score = 0.0

        reasons = []

        rsi = self._num(
            row,
            "RSI",
            "rsi",
        )

        previous_rsi = self._num(
            previous,
            "RSI",
            "rsi",
        )

        macd = self._num(
            row,
            "MACD",
            "macd",
        )

        macd_signal = self._num(
            row,
            "MACD_SIGNAL",
            "MACD_Signal",
            "macd_signal",
        )

        adx = self._num(
            row,
            "ADX",
            "adx",
        )

        plus_di = self._num(
            row,
            "+DI",
            "PLUS_DI",
            "plus_di",
        )

        minus_di = self._num(
            row,
            "-DI",
            "MINUS_DI",
            "minus_di",
        )

        if rsi is not None:

            if 55 <= rsi <= 70:

                score += 8

                reasons.append(
                    "Bullish momentum regime"
                )

            elif 50 <= rsi < 55:

                score += 4

            elif rsi < 35:

                score += 2

                reasons.append(
                    "Weak momentum / possible oversold condition"
                )

            elif rsi > 75:

                score += 2

                reasons.append(
                    "Momentum overheated"
                )

            if (
                previous_rsi is not None
                and rsi > previous_rsi
            ):

                score += 2

        if (
            macd is not None
            and macd_signal is not None
        ):

            if macd > macd_signal:

                score += 5

                reasons.append(
                    "MACD bullish"
                )

            else:

                score = max(
                    0,
                    score - 2,
                )

        if (
            adx is not None
            and adx >= 25
        ):

            score += 3

            reasons.append(
                "Strong trend strength"
            )

        if (
            plus_di is not None
            and minus_di is not None
            and plus_di > minus_di
        ):

            score += 2

        return (
            min(
                20,
                score,
            ),
            reasons,
        )

    # =========================================================
    # VOLATILITY — 20
    # =========================================================

    def _volatility_score(
        self,
        row,
    ):

        score = 0.0

        reasons = []

        atr_pct = self._num(
            row,
            "ATR_PERCENT",
            "atr_percent",
        )

        bb_width = self._num(
            row,
            "BB_WIDTH",
            "bb_width",
        )

        if atr_pct is not None:

            if 1 <= atr_pct <= 4:

                score += 15

                reasons.append(
                    "Healthy volatility environment"
                )

            elif atr_pct < 1:

                score += 10

                reasons.append(
                    "Low-volatility environment"
                )

            elif atr_pct <= 6:

                score += 8

                reasons.append(
                    "Elevated volatility"
                )

            else:

                score += 2

                reasons.append(
                    "Extreme volatility"
                )

        if bb_width is not None:

            if bb_width < 0.05:

                score += 5

                reasons.append(
                    "Volatility compression"
                )

            elif bb_width > 0.20:

                score += 1

                reasons.append(
                    "Volatility expansion"
                )

        return (
            min(
                20,
                score,
            ),
            reasons,
        )

    # =========================================================
    # PARTICIPATION — 15
    # =========================================================

    def _participation_score(
        self,
        row,
    ):

        score = 0.0

        reasons = []

        rvol = self._num(
            row,
            "RVOL",
            "rvol",
        )

        volume = self._num(
            row,
            "volume",
            "Volume",
        )

        volume_sma = self._num(
            row,
            "VOL_SMA_20",
            "volume_sma_20",
            "Volume_SMA_20",
        )

        if (
            rvol is not None
        ):

            if rvol >= 1.5:

                score += 10

                reasons.append(
                    "Strong market participation"
                )

            elif rvol >= 1:

                score += 7

            elif rvol >= 0.75:

                score += 4

            else:

                score += 1

                reasons.append(
                    "Low market participation"
                )

        if (
            volume is not None
            and volume_sma is not None
            and volume > volume_sma
        ):

            score += 5

            reasons.append(
                "Volume above average"
            )

        return (
            min(
                15,
                score,
            ),
            reasons,
        )

    # =========================================================
    # BREADTH — 15
    # =========================================================

    def _breadth_score(
        self,
        stock,
    ):

        score = 0.0

        reasons = []

        breadth = stock.get(
            "breadth"
        )

        if isinstance(
            breadth,
            dict,
        ):

            advancing = breadth.get(
                "advancing",
                0,
            )

            declining = breadth.get(
                "declining",
                0,
            )

            total = (
                advancing
                + declining
            )

            if total > 0:

                ratio = (
                    advancing
                    / total
                )

                if ratio >= 0.70:

                    score = 15

                    reasons.append(
                        "Strong positive market breadth"
                    )

                elif ratio >= 0.55:

                    score = 11

                    reasons.append(
                        "Positive market breadth"
                    )

                elif ratio >= 0.45:

                    score = 7

                    reasons.append(
                        "Balanced market breadth"
                    )

                elif ratio >= 0.30:

                    score = 3

                    reasons.append(
                        "Negative market breadth"
                    )

                else:

                    score = 0

                    reasons.append(
                        "Severely negative market breadth"
                    )

        else:

            # No breadth data should never be treated
            # as positive confirmation.

            score = 5

            reasons.append(
                "Market breadth unavailable"
            )

        return (
            min(
                15,
                score,
            ),
            reasons,
        )

    # =========================================================
    # REGIME
    # =========================================================

    def _regime(
        self,
        row,
        score,
    ):

        atr_pct = self._num(
            row,
            "ATR_PERCENT",
            "atr_percent",
        )

        adx = self._num(
            row,
            "ADX",
            "adx",
        )

        close = self._num(
            row,
            "close",
            "Close",
        )

        ema50 = self._num(
            row,
            "EMA_50",
            "ema_50",
        )

        ema200 = self._num(
            row,
            "EMA_200",
            "ema_200",
        )

        # Risk-off takes priority.

        if (
            atr_pct is not None
            and atr_pct > 7
        ):

            return "RISK_OFF"

        if (
            score < 35
        ):

            return "RISK_OFF"

        if (
            atr_pct is not None
            and atr_pct > 5
        ):

            return "HIGH_VOLATILITY"

        if (
            close is not None
            and ema50 is not None
            and ema200 is not None
        ):

            if (
                close > ema50 > ema200
                and score >= 65
            ):

                return "BULLISH"

            if (
                close < ema50 < ema200
                and score < 55
            ):

                return "BEARISH"

        if (
            adx is not None
            and adx < 15
        ):

            return "SIDEWAYS"

        if score >= 65:

            return "BULLISH"

        if score < 50:

            return "BEARISH"

        return "SIDEWAYS"

    # =========================================================
    # DIRECTION
    # =========================================================

    def _direction(
        self,
        row,
    ):

        bullish = 0

        bearish = 0

        if self._flag(
            row,
            "UPTREND",
        ):

            bullish += 2

        if self._flag(
            row,
            "BREAKOUT",
        ):

            bullish += 2

        if self._flag(
            row,
            "DOWNTREND",
        ):

            bearish += 2

        if self._flag(
            row,
            "BREAKDOWN",
        ):

            bearish += 2

        close = self._num(
            row,
            "close",
            "Close",
        )

        ema50 = self._num(
            row,
            "EMA_50",
            "ema_50",
        )

        ema200 = self._num(
            row,
            "EMA_200",
            "ema_200",
        )

        if (
            close is not None
            and ema50 is not None
        ):

            if close > ema50:

                bullish += 1

            else:

                bearish += 1

        if (
            close is not None
            and ema200 is not None
        ):

            if close > ema200:

                bullish += 1

            else:

                bearish += 1

        if bullish > bearish:

            return "BULLISH"

        if bearish > bullish:

            return "BEARISH"

        return "NEUTRAL"

    # =========================================================
    # WARNINGS
    # =========================================================

    def _warnings(
        self,
        row,
        regime,
    ):

        warnings = []

        if regime == "RISK_OFF":

            warnings.append(
                "Risk-off regime: block aggressive entries"
            )

        if regime == "HIGH_VOLATILITY":

            warnings.append(
                "High volatility: reduce position size"
            )

        if regime == "SIDEWAYS":

            warnings.append(
                "Sideways regime: breakout confirmation required"
            )

        rvol = self._num(
            row,
            "RVOL",
            "rvol",
        )

        if (
            rvol is not None
            and rvol < 0.75
        ):

            warnings.append(
                "Weak participation"
            )

        adx = self._num(
            row,
            "ADX",
            "adx",
        )

        if (
            adx is not None
            and adx < 15
        ):

            warnings.append(
                "ADX below 15: no strong trend"
            )

        return warnings

    # =========================================================
    # CONFIDENCE
    # =========================================================

    def _confidence(
        self,
        row,
        score,
    ):

        required = (

            "EMA_20",
            "EMA_50",
            "EMA_200",
            "RSI",
            "ADX",
            "ATR_PERCENT",
            "RVOL",

        )

        available = 0

        for key in required:

            value = self._num(
                row,
                key,
            )

            if value is not None:

                available += 1

        completeness = (
            available
            / len(required)
        )

        confidence = (
            score
            * (
                0.70
                + 0.30
                * completeness
            )
        )

        return round(
            max(
                0,
                min(
                    100,
                    confidence,
                ),
            ),
            2,
        )

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self):

        return {

            "status": "healthy",

            "engine": self.NAME,

            "weights": {

                "trend": 30,

                "momentum": 20,

                "volatility": 20,

                "participation": 15,

                "breadth": 15,

            },

            "regimes": [

                "BULLISH",
                "BEARISH",
                "SIDEWAYS",
                "HIGH_VOLATILITY",
                "RISK_OFF",

            ],

        }