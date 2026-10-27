"""
TrendForge v2
Candlestick Pattern Recognition
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


class CandlestickPatterns:

    # --------------------------------------------------
    # Candle Components
    # --------------------------------------------------

    @staticmethod
    def _body(df):

        return (df["close"] - df["open"]).abs()

    @staticmethod
    def _upper_shadow(df):

        return df["high"] - df[["open", "close"]].max(axis=1)

    @staticmethod
    def _lower_shadow(df):

        return df[["open", "close"]].min(axis=1) - df["low"]

    @staticmethod
    def _range(df):

        return df["high"] - df["low"]

    # --------------------------------------------------
    # Doji
    # --------------------------------------------------

    @staticmethod
    def add_doji(df):

        body = CandlestickPatterns._body(df)

        rng = CandlestickPatterns._range(df)

        df["DOJI"] = body <= rng * 0.10

        return df

    # --------------------------------------------------
    # Hammer
    # --------------------------------------------------

    @staticmethod
    def add_hammer(df):

        body = CandlestickPatterns._body(df)

        lower = CandlestickPatterns._lower_shadow(df)

        upper = CandlestickPatterns._upper_shadow(df)

        df["HAMMER"] = (
            (lower >= body * 2)
            &
            (upper <= body)
        )

        return df

    # --------------------------------------------------
    # Inverted Hammer
    # --------------------------------------------------

    @staticmethod
    def add_inverted_hammer(df):

        body = CandlestickPatterns._body(df)

        lower = CandlestickPatterns._lower_shadow(df)

        upper = CandlestickPatterns._upper_shadow(df)

        df["INVERTED_HAMMER"] = (
            (upper >= body * 2)
            &
            (lower <= body)
        )

        return df

    # --------------------------------------------------
    # Bullish Engulfing
    # --------------------------------------------------

    @staticmethod
    def add_bullish_engulfing(df):

        prev_open = df["open"].shift()

        prev_close = df["close"].shift()

        df["BULLISH_ENGULFING"] = (

            (prev_close < prev_open)

            &

            (df["close"] > df["open"])

            &

            (df["open"] < prev_close)

            &

            (df["close"] > prev_open)

        )

        return df

    # --------------------------------------------------
    # Bearish Engulfing
    # --------------------------------------------------

    @staticmethod
    def add_bearish_engulfing(df):

        prev_open = df["open"].shift()

        prev_close = df["close"].shift()

        df["BEARISH_ENGULFING"] = (

            (prev_close > prev_open)

            &

            (df["close"] < df["open"])

            &

            (df["open"] > prev_close)

            &

            (df["close"] < prev_open)

        )

        return df

    # --------------------------------------------------
    # Marubozu
    # --------------------------------------------------

    @staticmethod
    def add_marubozu(df):

        body = CandlestickPatterns._body(df)

        rng = CandlestickPatterns._range(df)

        df["MARUBOZU"] = body >= rng * 0.90

        return df

    # --------------------------------------------------
    # Shooting Star
    # --------------------------------------------------

    @staticmethod
    def add_shooting_star(df):

        body = CandlestickPatterns._body(df)

        upper = CandlestickPatterns._upper_shadow(df)

        lower = CandlestickPatterns._lower_shadow(df)

        df["SHOOTING_STAR"] = (

            (upper >= body * 2)

            &

            (lower <= body * 0.5)

        )

        return df

    # --------------------------------------------------
    # Hanging Man
    # --------------------------------------------------

    @staticmethod
    def add_hanging_man(df):

        body = CandlestickPatterns._body(df)

        lower = CandlestickPatterns._lower_shadow(df)

        upper = CandlestickPatterns._upper_shadow(df)

        df["HANGING_MAN"] = (

            (lower >= body * 2)

            &

            (upper <= body)

        )

        return df

    # --------------------------------------------------
    # Harami
    # --------------------------------------------------

    @staticmethod
    def add_harami(df):

        prev_high = df[["open", "close"]].shift().max(axis=1)

        prev_low = df[["open", "close"]].shift().min(axis=1)

        current_high = df[["open", "close"]].max(axis=1)

        current_low = df[["open", "close"]].min(axis=1)

        df["HARAMI"] = (

            (current_high < prev_high)

            &

            (current_low > prev_low)

        )

        return df

    # --------------------------------------------------
    # All Patterns
    # --------------------------------------------------

    @staticmethod
    def add_all(df):

        df = CandlestickPatterns.add_doji(df)

        df = CandlestickPatterns.add_hammer(df)

        df = CandlestickPatterns.add_inverted_hammer(df)

        df = CandlestickPatterns.add_bullish_engulfing(df)

        df = CandlestickPatterns.add_bearish_engulfing(df)

        df = CandlestickPatterns.add_marubozu(df)

        df = CandlestickPatterns.add_shooting_star(df)

        df = CandlestickPatterns.add_hanging_man(df)

        df = CandlestickPatterns.add_harami(df)

        return df