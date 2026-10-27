"""
TrendForge v2
Price Action Indicators
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


class PriceAction:

    # --------------------------------------------------
    # Higher High
    # --------------------------------------------------

    @staticmethod
    def add_higher_high(df):

        df["HIGHER_HIGH"] = (
            df["high"] >
            df["high"].shift()
        )

        return df

    # --------------------------------------------------
    # Lower Low
    # --------------------------------------------------

    @staticmethod
    def add_lower_low(df):

        df["LOWER_LOW"] = (
            df["low"] <
            df["low"].shift()
        )

        return df

    # --------------------------------------------------
    # Higher Low
    # --------------------------------------------------

    @staticmethod
    def add_higher_low(df):

        df["HIGHER_LOW"] = (
            df["low"] >
            df["low"].shift()
        )

        return df

    # --------------------------------------------------
    # Lower High
    # --------------------------------------------------

    @staticmethod
    def add_lower_high(df):

        df["LOWER_HIGH"] = (
            df["high"] <
            df["high"].shift()
        )

        return df

    # --------------------------------------------------
    # Swing High
    # --------------------------------------------------

    @staticmethod
    def add_swing_high(df, lookback=3):

        df["SWING_HIGH"] = (
            df["high"] ==
            df["high"].rolling(
                lookback * 2 + 1,
                center=True,
            ).max()
        )

        return df

    # --------------------------------------------------
    # Swing Low
    # --------------------------------------------------

    @staticmethod
    def add_swing_low(df, lookback=3):

        df["SWING_LOW"] = (
            df["low"] ==
            df["low"].rolling(
                lookback * 2 + 1,
                center=True,
            ).min()
        )

        return df

    # --------------------------------------------------
    # 20-Day Breakout
    # --------------------------------------------------

    @staticmethod
    def add_breakout(df, period=20):

        highest = (
            df["high"]
            .shift(1)
            .rolling(period)
            .max()
        )

        df["BREAKOUT"] = (
            df["close"] >
            highest
        )

        return df

    # --------------------------------------------------
    # 20-Day Breakdown
    # --------------------------------------------------

    @staticmethod
    def add_breakdown(df, period=20):

        lowest = (
            df["low"]
            .shift(1)
            .rolling(period)
            .min()
        )

        df["BREAKDOWN"] = (
            df["close"] <
            lowest
        )

        return df

    # --------------------------------------------------
    # Gap Up
    # --------------------------------------------------

    @staticmethod
    def add_gap_up(df):

        df["GAP_UP"] = (
            df["open"] >
            df["high"].shift()
        )

        return df

    # --------------------------------------------------
    # Gap Down
    # --------------------------------------------------

    @staticmethod
    def add_gap_down(df):

        df["GAP_DOWN"] = (
            df["open"] <
            df["low"].shift()
        )

        return df

    # --------------------------------------------------
    # Inside Bar
    # --------------------------------------------------

    @staticmethod
    def add_inside_bar(df):

        df["INSIDE_BAR"] = (

            (df["high"] <
             df["high"].shift())

            &

            (df["low"] >
             df["low"].shift())

        )

        return df

    # --------------------------------------------------
    # Outside Bar
    # --------------------------------------------------

    @staticmethod
    def add_outside_bar(df):

        df["OUTSIDE_BAR"] = (

            (df["high"] >
             df["high"].shift())

            &

            (df["low"] <
             df["low"].shift())

        )

        return df

    # --------------------------------------------------
    # NR7
    # --------------------------------------------------

    @staticmethod
    def add_nr7(df):

        rng = (
            df["high"] -
            df["low"]
        )

        df["NR7"] = (
            rng ==
            rng.rolling(7).min()
        )

        return df

    # --------------------------------------------------
    # Support
    # --------------------------------------------------

    @staticmethod
    def add_support(df, period=20):

        df["SUPPORT"] = (
            df["low"]
            .rolling(period)
            .min()
        )

        return df

    # --------------------------------------------------
    # Resistance
    # --------------------------------------------------

    @staticmethod
    def add_resistance(df, period=20):

        df["RESISTANCE"] = (
            df["high"]
            .rolling(period)
            .max()
        )

        return df

    # --------------------------------------------------
    # 52-Week Context
    # --------------------------------------------------

    @staticmethod
    def add_52week_context(df, period=252):
        df["HIGH_252"] = df["high"].shift(1).rolling(period).max()
        df["LOW_252"] = df["low"].shift(1).rolling(period).min()
        df["DIST_52W_HIGH_PCT"] = (
            (df["HIGH_252"] - df["close"])
            / df["HIGH_252"].replace(0, float("nan"))
            * 100.0
        )
        return df

    # --------------------------------------------------
    # Trend
    # --------------------------------------------------

    @staticmethod
    def add_trend(df):

        df["UPTREND"] = (

            (df["HIGHER_HIGH"])

            &

            (df["HIGHER_LOW"])

        )

        df["DOWNTREND"] = (

            (df["LOWER_HIGH"])

            &

            (df["LOWER_LOW"])

        )

        return df

    # --------------------------------------------------
    # ALL
    # --------------------------------------------------

    @staticmethod
    def add_all(df):

        df = PriceAction.add_higher_high(df)

        df = PriceAction.add_higher_low(df)

        df = PriceAction.add_lower_high(df)

        df = PriceAction.add_lower_low(df)

        df = PriceAction.add_swing_high(df)

        df = PriceAction.add_swing_low(df)

        df = PriceAction.add_breakout(df)

        df = PriceAction.add_breakdown(df)

        df = PriceAction.add_gap_up(df)

        df = PriceAction.add_gap_down(df)

        df = PriceAction.add_inside_bar(df)

        df = PriceAction.add_outside_bar(df)

        df = PriceAction.add_nr7(df)

        df = PriceAction.add_support(df)

        df = PriceAction.add_resistance(df)

        df = PriceAction.add_52week_context(df)

        df = PriceAction.add_trend(df)

        return df