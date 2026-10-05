"""
TrendForge v2
Price Action Engine

Purpose:
    Convert existing IndicatorEngine price-action columns into a
    normalized 0-100 price-action quality score.

Designed for:
    - Intraday
    - Short swing
    - Short term
    - Breakout / breakdown detection
    - Support / resistance
    - Market structure
    - Pivot levels
    - Candlestick confirmation
    - Volume-confirmed price action

This engine does NOT create a final BUY/SELL decision.
The Signal Engine combines it with Technical, Fundamental,
Risk, Corporate Action and Big Shark scores.
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from indicators.indicator_engine import IndicatorEngine


class PriceActionEngine(BaseEngine):

    NAME = "Price Action Engine"

    # Maximum points
    STRUCTURE_MAX = 25
    BREAKOUT_MAX = 25
    SUPPORT_RESISTANCE_MAX = 20
    CANDLE_MAX = 15
    PIVOT_MAX = 15

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

            value = row.get(
                key,
                False,
            )

            try:

                if (
                    value is not None
                    and not pd.isna(value)
                    and bool(value)
                ):

                    return True

            except (TypeError, ValueError):
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
    # MAIN ENGINE
    # =========================================================

    def evaluate(
        self,
        stock: Dict[str, Any],
    ) -> EngineResult:

        df = self._frame(stock)

        if df is None:

            return EngineResult(

                engine=self.NAME,

                passed=False,

                score=0.0,

                confidence=0.0,

                grade="D",

                warnings=[
                    "OHLCV DataFrame not supplied."
                ],

            )

        if len(df) < 30:

            return EngineResult(

                engine=self.NAME,

                passed=False,

                score=0.0,

                confidence=0.0,

                grade="D",

                warnings=[
                    "Minimum 30 candles required."
                ],

            )

        # IndicatorEngine is owned by FullScannerPipeline.
        # This engine consumes the already-enriched dataframe.
        row = df.iloc[-1]

        previous = df.iloc[-2]

        structure, structure_reasons = (
            self._structure_score(
                row,
                previous,
            )
        )

        breakout, breakout_reasons = (
            self._breakout_score(
                df,
                row,
                previous,
            )
        )

        sr, sr_reasons = (
            self._support_resistance_score(
                df,
                row,
            )
        )

        candle, candle_reasons = (
            self._candlestick_score(
                row,
            )
        )

        pivot, pivot_reasons = (
            self._pivot_score(
                df,
                row,
            )
        )

        score = round(
            structure
            + breakout
            + sr
            + candle
            + pivot,
            2,
        )

        reasons = (
            structure_reasons
            + breakout_reasons
            + sr_reasons
            + candle_reasons
            + pivot_reasons
        )

        warnings = self._warnings(
            row,
            score,
        )

        confidence = self._confidence(
            row,
            score,
        )

        direction = self._direction(
            row,
        )

        metrics = self._metrics(
            df,
            row,
            score,
            direction,
            structure,
            breakout,
            sr,
            candle,
            pivot,
        )

        return EngineResult(

            engine=self.NAME,

            passed=(
                score >= 65
                and direction != "BEARISH"
            ),

            score=score,

            confidence=confidence,

            grade=self._grade(score),

            reasons=reasons[:25],

            warnings=warnings,

            metrics=metrics,

        )

    # =========================================================
    # MARKET STRUCTURE — 25
    # =========================================================

    def _structure_score(
        self,
        row,
        previous,
    ):

        score = 0.0

        reasons = []

        hh = self._flag(
            row,
            "HIGHER_HIGH",
        )

        hl = self._flag(
            row,
            "HIGHER_LOW",
        )

        lh = self._flag(
            row,
            "LOWER_HIGH",
        )

        ll = self._flag(
            row,
            "LOWER_LOW",
        )

        uptrend = self._flag(
            row,
            "UPTREND",
        )

        downtrend = self._flag(
            row,
            "DOWNTREND",
        )

        # Strong bullish structure

        if hh and hl:

            score += 15

            reasons.append(
                "Higher-high and higher-low structure"
            )

        elif hh:

            score += 7

            reasons.append(
                "Higher-high detected"
            )

        elif hl:

            score += 6

            reasons.append(
                "Higher-low detected"
            )

        # Strong bearish structure

        if lh and ll:

            score -= 15

            reasons.append(
                "Lower-high and lower-low structure"
            )

        elif lh:

            score -= 7

        elif ll:

            score -= 7

        if uptrend:

            score += 10

            reasons.append(
                "Confirmed price uptrend"
            )

        if downtrend:

            score -= 10

            reasons.append(
                "Confirmed price downtrend"
            )

        return (
            max(
                0,
                min(
                    self.STRUCTURE_MAX,
                    score,
                ),
            ),
            reasons,
        )

    # =========================================================
    # BREAKOUT / BREAKDOWN — 25
    # =========================================================

    def _breakout_score(
        self,
        df,
        row,
        previous,
    ):

        score = 0.0

        reasons = []

        breakout = self._flag(
            row,
            "BREAKOUT",
        )

        breakdown = self._flag(
            row,
            "BREAKDOWN",
        )

        close = self._num(
            row,
            "close",
            "Close",
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

        rvol = self._num(
            row,
            "RVOL",
            "rvol",
        )

        resistance = self._num(
            row,
            "RESISTANCE",
            "resistance",
        )

        support = self._num(
            row,
            "SUPPORT",
            "support",
        )

        # -----------------------------------------------------
        # BREAKOUT
        # -----------------------------------------------------

        if breakout:

            score += 12

            reasons.append(
                "20-period breakout detected"
            )

            if (
                rvol is not None
                and rvol >= 2
            ):

                score += 7

                reasons.append(
                    "Breakout supported by >=2x relative volume"
                )

            elif (
                rvol is not None
                and rvol >= 1.5
            ):

                score += 5

                reasons.append(
                    "Breakout supported by above-average volume"
                )

            elif (
                volume is not None
                and volume_sma is not None
                and volume > volume_sma
            ):

                score += 3

                reasons.append(
                    "Breakout volume above average"
                )

            if (
                close is not None
                and resistance is not None
                and close > resistance
            ):

                score += 6

                reasons.append(
                    "Close above resistance"
                )

        # -----------------------------------------------------
        # BREAKDOWN
        # -----------------------------------------------------

        if breakdown:

            score -= 15

            reasons.append(
                "20-period breakdown detected"
            )

            if (
                rvol is not None
                and rvol >= 1.5
            ):

                score -= 5

                reasons.append(
                    "Breakdown supported by strong volume"
                )

            if (
                close is not None
                and support is not None
                and close < support
            ):

                score -= 5

                reasons.append(
                    "Close below support"
                )

        return (
            max(
                0,
                min(
                    self.BREAKOUT_MAX,
                    score,
                ),
            ),
            reasons,
        )

    # =========================================================
    # SUPPORT / RESISTANCE — 20
    # =========================================================

    def _support_resistance_score(
        self,
        df,
        row,
    ):

        score = 0.0

        reasons = []

        close = self._num(
            row,
            "close",
            "Close",
        )

        support = self._num(
            row,
            "SUPPORT",
            "support",
        )

        resistance = self._num(
            row,
            "RESISTANCE",
            "resistance",
        )

        if close is None:

            return 0.0, reasons

        # -----------------------------------------------------
        # Near support
        # -----------------------------------------------------

        if (
            support is not None
            and support > 0
        ):

            support_distance = (
                abs(close - support)
                / close
            )

            if support_distance <= 0.01:

                score += 10

                reasons.append(
                    "Price within 1% of support"
                )

            elif support_distance <= 0.02:

                score += 7

                reasons.append(
                    "Price within 2% of support"
                )

            elif support_distance <= 0.03:

                score += 4

        # -----------------------------------------------------
        # Near resistance
        # -----------------------------------------------------

        if (
            resistance is not None
            and resistance > 0
        ):

            resistance_distance = (
                abs(resistance - close)
                / close
            )

            if resistance_distance <= 0.01:

                reasons.append(
                    "Price within 1% of resistance"
                )

            elif resistance_distance <= 0.02:

                reasons.append(
                    "Price within 2% of resistance"
                )

        # -----------------------------------------------------
        # Breakout above resistance
        # -----------------------------------------------------

        if (
            resistance is not None
            and close > resistance
        ):

            score += 10

            reasons.append(
                "Price accepted above resistance"
            )

        # -----------------------------------------------------
        # Breakdown below support
        # -----------------------------------------------------

        if (
            support is not None
            and close < support
        ):

            score -= 10

            reasons.append(
                "Price below support"
            )

        return (
            max(
                0,
                min(
                    self.SUPPORT_RESISTANCE_MAX,
                    score,
                ),
            ),
            reasons,
        )

    # =========================================================
    # CANDLESTICKS — 15
    # =========================================================

    def _candlestick_score(
        self,
        row,
    ):

        score = 0.0

        reasons = []

        bullish_engulfing = self._flag(
            row,
            "BULLISH_ENGULFING",
        )

        bearish_engulfing = self._flag(
            row,
            "BEARISH_ENGULFING",
        )

        hammer = self._flag(
            row,
            "HAMMER",
        )

        doji = self._flag(
            row,
            "DOJI",
        )

        inside_bar = self._flag(
            row,
            "INSIDE_BAR",
        )

        outside_bar = self._flag(
            row,
            "OUTSIDE_BAR",
        )

        nr7 = self._flag(
            row,
            "NR7",
        )

        gap_up = self._flag(
            row,
            "GAP_UP",
        )

        gap_down = self._flag(
            row,
            "GAP_DOWN",
        )

        if bullish_engulfing:

            score += 6

            reasons.append(
                "Bullish engulfing confirmation"
            )

        if hammer:

            score += 4

            reasons.append(
                "Hammer confirmation"
            )

        if bearish_engulfing:

            score -= 6

            reasons.append(
                "Bearish engulfing warning"
            )

        if doji:

            score -= 1

            reasons.append(
                "Doji indicates indecision"
            )

        if inside_bar:

            score += 2

            reasons.append(
                "Inside-bar compression"
            )

        if outside_bar:

            score += 2

            reasons.append(
                "Outside-bar expansion"
            )

        if nr7:

            score += 2

            reasons.append(
                "NR7 volatility compression"
            )

        if gap_up:

            score += 3

            reasons.append(
                "Gap-up price strength"
            )

        if gap_down:

            score -= 3

            reasons.append(
                "Gap-down weakness"
            )

        return (
            max(
                0,
                min(
                    self.CANDLE_MAX,
                    score,
                ),
            ),
            reasons,
        )

    # =========================================================
    # PIVOTS — 15
    # =========================================================

    def _pivot_score(
        self,
        df,
        row,
    ):

        score = 0.0

        reasons = []

        if len(df) < 2:

            return 0.0, reasons

        previous = df.iloc[-2]

        high = self._num(
            previous,
            "high",
            "High",
        )

        low = self._num(
            previous,
            "low",
            "Low",
        )

        close = self._num(
            previous,
            "close",
            "Close",
        )

        current_close = self._num(
            row,
            "close",
            "Close",
        )

        if not all(
            value is not None
            for value in (
                high,
                low,
                close,
                current_close,
            )
        ):

            return 0.0, reasons

        pivot = (
            high
            + low
            + close
        ) / 3

        r1 = (
            2 * pivot
            - low
        )

        s1 = (
            2 * pivot
            - high
        )

        r2 = (
            pivot
            + (high - low)
        )

        s2 = (
            pivot
            - (high - low)
        )

        # Strong bullish acceptance

        if current_close > r2:

            score += 15

            reasons.append(
                "Price above Pivot R2"
            )

        elif current_close > r1:

            score += 10

            reasons.append(
                "Price above Pivot R1"
            )

        elif current_close > pivot:

            score += 6

            reasons.append(
                "Price above daily pivot"
            )

        # Bearish

        elif current_close < s2:

            score = 0

            reasons.append(
                "Price below Pivot S2"
            )

        elif current_close < s1:

            score = 1

            reasons.append(
                "Price below Pivot S1"
            )

        return (
            min(
                self.PIVOT_MAX,
                score,
            ),
            reasons,
        )

    # =========================================================
    # DIRECTION
    # =========================================================

    def _direction(
        self,
        row,
    ) -> str:

        bullish = 0

        bearish = 0

        if self._flag(
            row,
            "HIGHER_HIGH",
        ):

            bullish += 1

        if self._flag(
            row,
            "HIGHER_LOW",
        ):

            bullish += 1

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
            "LOWER_HIGH",
        ):

            bearish += 1

        if self._flag(
            row,
            "LOWER_LOW",
        ):

            bearish += 1

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

        if bullish > bearish:

            return "BULLISH"

        if bearish > bullish:

            return "BEARISH"

        return "NEUTRAL"

    # =========================================================
    # CONFIDENCE
    # =========================================================

    def _confidence(
        self,
        row,
        score,
    ):

        required = (

            "HIGHER_HIGH",
            "HIGHER_LOW",
            "LOWER_HIGH",
            "LOWER_LOW",
            "BREAKOUT",
            "BREAKDOWN",
            "SUPPORT",
            "RESISTANCE",
            "RVOL",
            "UPTREND",

        )

        available = 0

        for key in required:

            if key in row.index:

                value = row.get(key)

                if value is not None:

                    try:

                        if not pd.isna(value):

                            available += 1

                    except TypeError:

                        available += 1

        completeness = (
            available
            / len(required)
        )

        confidence = (
            score
            * (
                0.70
                + 0.30 * completeness
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
    # WARNINGS
    # =========================================================

    def _warnings(
        self,
        row,
        score,
    ):

        warnings = []

        if self._flag(
            row,
            "BREAKDOWN",
        ):

            warnings.append(
                "Breakdown detected"
            )

        if self._flag(
            row,
            "GAP_DOWN",
        ):

            warnings.append(
                "Gap-down weakness"
            )

        if self._flag(
            row,
            "DOJI",
        ):

            warnings.append(
                "Indecision candle"
            )

        if self._flag(
            row,
            "BEARISH_ENGULFING",
        ):

            warnings.append(
                "Bearish engulfing pattern"
            )

        if score < 60:

            warnings.append(
                "Weak price-action setup"
            )

        return warnings

    # =========================================================
    # METRICS
    # =========================================================

    def _metrics(
        self,
        df,
        row,
        score,
        direction,
        structure,
        breakout,
        sr,
        candle,
        pivot,
    ):

        close = self._num(
            row,
            "close",
            "Close",
        )

        support = self._num(
            row,
            "SUPPORT",
            "support",
        )

        resistance = self._num(
            row,
            "RESISTANCE",
            "resistance",
        )

        metrics = {

            "score": score,

            "direction": direction,

            "structure_score": structure,

            "breakout_score": breakout,

            "support_resistance_score": sr,

            "candlestick_score": candle,

            "pivot_score": pivot,

            "close": close,

            "support": support,

            "resistance": resistance,

            "breakout": self._flag(
                row,
                "BREAKOUT",
            ),

            "breakdown": self._flag(
                row,
                "BREAKDOWN",
            ),

            "uptrend": self._flag(
                row,
                "UPTREND",
            ),

            "downtrend": self._flag(
                row,
                "DOWNTREND",
            ),

            "higher_high": self._flag(
                row,
                "HIGHER_HIGH",
            ),

            "higher_low": self._flag(
                row,
                "HIGHER_LOW",
            ),

            "lower_high": self._flag(
                row,
                "LOWER_HIGH",
            ),

            "lower_low": self._flag(
                row,
                "LOWER_LOW",
            ),

            "gap_up": self._flag(
                row,
                "GAP_UP",
            ),

            "gap_down": self._flag(
                row,
                "GAP_DOWN",
            ),

            "inside_bar": self._flag(
                row,
                "INSIDE_BAR",
            ),

            "outside_bar": self._flag(
                row,
                "OUTSIDE_BAR",
            ),

            "nr7": self._flag(
                row,
                "NR7",
            ),

            "bullish_engulfing": self._flag(
                row,
                "BULLISH_ENGULFING",
            ),

            "bearish_engulfing": self._flag(
                row,
                "BEARISH_ENGULFING",
            ),

            "hammer": self._flag(
                row,
                "HAMMER",
            ),

            "doji": self._flag(
                row,
                "DOJI",
            ),

        }

        # Current candle range

        high = self._num(
            row,
            "high",
            "High",
        )

        low = self._num(
            row,
            "low",
            "Low",
        )

        if (
            high is not None
            and low is not None
            and close is not None
            and high > low
        ):

            metrics["range"] = (
                high - low
            )

            metrics["close_location"] = round(
                (
                    close - low
                )
                /
                (
                    high - low
                ),
                4,
            )

        return metrics

    # =========================================================
    # HEALTH
    # =========================================================

    def health(self):

        return {

            "status": "healthy",

            "engine": self.NAME,

            "weights": {

                "structure": self.STRUCTURE_MAX,

                "breakout": self.BREAKOUT_MAX,

                "support_resistance":
                    self.SUPPORT_RESISTANCE_MAX,

                "candlestick":
                    self.CANDLE_MAX,

                "pivot":
                    self.PIVOT_MAX,

            },

        }