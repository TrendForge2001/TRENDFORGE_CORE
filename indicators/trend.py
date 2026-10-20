"""
TrendForge v2
Trend Indicators
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TrendIndicators:
    """
    Trend Indicators

    EMA
    SMA
    """

    @staticmethod
    def ema(
        df: pd.DataFrame,
        length: int,
    ) -> pd.Series:

        return df["close"].ewm(
            span=length,
            adjust=False,
        ).mean()

    @staticmethod
    def sma(
        df: pd.DataFrame,
        length: int,
    ) -> pd.Series:

        return (
            df["close"]
            .rolling(length)
            .mean()
        )

    @staticmethod
    def add_ema(
        df: pd.DataFrame,
        length: int,
    ) -> pd.DataFrame:

        df[f"EMA_{length}"] = (
            TrendIndicators.ema(
                df,
                length,
            )
        )

        return df

    @staticmethod
    def add_sma(
        df: pd.DataFrame,
        length: int,
    ) -> pd.DataFrame:

        df[f"SMA_{length}"] = (
            TrendIndicators.sma(
                df,
                length,
            )
        )

        return df

    @staticmethod
    def add_supertrend(
        df: pd.DataFrame,
        length: int = 10,
        multiplier: float = 3.0,
    ) -> pd.DataFrame:
        """Add a standard ATR Supertrend line and +1/-1 direction."""
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        previous_close = close.shift(1)
        true_range = pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(length).mean()
        midpoint = (high + low) / 2.0
        basic_upper = midpoint + multiplier * atr
        basic_lower = midpoint - multiplier * atr
        final_upper = basic_upper.copy()
        final_lower = basic_lower.copy()
        supertrend = pd.Series(float("nan"), index=df.index, dtype=float)
        direction = pd.Series(0, index=df.index, dtype=int)

        for i in range(1, len(df)):
            if pd.isna(atr.iloc[i]):
                continue
            prev_upper = final_upper.iloc[i - 1]
            prev_lower = final_lower.iloc[i - 1]
            if pd.isna(prev_upper):
                prev_upper = basic_upper.iloc[i]
            if pd.isna(prev_lower):
                prev_lower = basic_lower.iloc[i]

            final_upper.iloc[i] = (
                basic_upper.iloc[i]
                if basic_upper.iloc[i] < prev_upper
                or close.iloc[i - 1] > prev_upper
                else prev_upper
            )
            final_lower.iloc[i] = (
                basic_lower.iloc[i]
                if basic_lower.iloc[i] > prev_lower
                or close.iloc[i - 1] < prev_lower
                else prev_lower
            )

            previous_st = supertrend.iloc[i - 1]
            if pd.isna(previous_st):
                previous_st = final_upper.iloc[i - 1]
            if previous_st == final_upper.iloc[i - 1]:
                supertrend.iloc[i] = (
                    final_upper.iloc[i]
                    if close.iloc[i] <= final_upper.iloc[i]
                    else final_lower.iloc[i]
                )
            else:
                supertrend.iloc[i] = (
                    final_lower.iloc[i]
                    if close.iloc[i] >= final_lower.iloc[i]
                    else final_upper.iloc[i]
                )
            direction.iloc[i] = (
                1 if close.iloc[i] >= supertrend.iloc[i] else -1
            )

        suffix = f"{length}_{str(multiplier).replace('.', '_')}"
        if length == 10 and float(multiplier) == 3.0:
            suffix = "10_3"
        df[f"SUPERTREND_{suffix}"] = supertrend
        df["SUPERTREND_DIR"] = direction
        return df

    @staticmethod
    def add_all_emas(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        for length in (
            9,
            20,
            50,
            100,
            200,
        ):

            df = TrendIndicators.add_ema(
                df,
                length,
            )

        return df

    @staticmethod
    def add_all_smas(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        for length in (
            20,
            50,
            100,
            200,
        ):

            df = TrendIndicators.add_sma(
                df,
                length,
            )

        return df