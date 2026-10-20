"""Fibonacci pivot-point indicators used by TrendForge strategies."""
from __future__ import annotations

import pandas as pd


class FibonacciPivots:
    """Previous-bar Fibonacci pivots.

    R72.5.1 provides the canonical calculation.  R72.5.2 will choose the
    aggregation source (daily/weekly/monthly) per strategy before evaluation.
    """

    @staticmethod
    def add_all(df: pd.DataFrame) -> pd.DataFrame:
        previous_high = df["high"].shift(1).astype(float)
        previous_low = df["low"].shift(1).astype(float)
        previous_close = df["close"].shift(1).astype(float)
        pivot = (previous_high + previous_low + previous_close) / 3.0
        spread = previous_high - previous_low

        df["FIB_PIVOT"] = pivot
        df["FIB_R1"] = pivot + 0.382 * spread
        df["FIB_R2"] = pivot + 0.618 * spread
        df["FIB_R3"] = pivot + 1.000 * spread
        df["FIB_S1"] = pivot - 0.382 * spread
        df["FIB_S2"] = pivot - 0.618 * spread
        df["FIB_S3"] = pivot - 1.000 * spread
        return df


__all__ = ["FibonacciPivots"]
