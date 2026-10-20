"""
TrendForge v2
Volume Indicators
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


class VolumeIndicators:
    """
    Volume Indicators

    ✓ Volume SMA
    ✓ Relative Volume (RVOL)
    ✓ VWAP
    ✓ OBV
    ✓ ADL
    ✓ CMF
    ✓ MFI
    """

    # --------------------------------------------------
    # Volume SMA
    # --------------------------------------------------

    @staticmethod
    def add_volume_sma(
        df: pd.DataFrame,
        length: int = 20,
    ) -> pd.DataFrame:

        df[f"VOL_SMA_{length}"] = (
            df["volume"]
            .rolling(length)
            .mean()
        )

        return df

    # --------------------------------------------------
    # Relative Volume
    # --------------------------------------------------

    @staticmethod
    def add_rvol(
        df: pd.DataFrame,
        length: int = 20,
    ) -> pd.DataFrame:

        if f"VOL_SMA_{length}" not in df.columns:

            df = VolumeIndicators.add_volume_sma(
                df,
                length,
            )

        df["RVOL"] = (
            df["volume"]
            /
            df[f"VOL_SMA_{length}"]
        )

        return df

    # --------------------------------------------------
    # VWAP
    # --------------------------------------------------

    @staticmethod
    def add_vwap(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        typical_price = (
            df["high"] +
            df["low"] +
            df["close"]
        ) / 3

        cumulative_tp = (
            typical_price *
            df["volume"]
        ).cumsum()

        cumulative_volume = (
            df["volume"]
            .cumsum()
        )

        df["VWAP"] = (
            cumulative_tp /
            cumulative_volume
        )

        return df

    # --------------------------------------------------
    # OBV
    # --------------------------------------------------

    @staticmethod
    def add_obv(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        direction = (
            df["close"]
            .diff()
            .fillna(0)
        )

        direction = direction.apply(
            lambda x: 1 if x > 0 else (
                -1 if x < 0 else 0
            )
        )

        df["OBV"] = (
            direction *
            df["volume"]
        ).cumsum()

        return df

    # --------------------------------------------------
    # ADL
    # --------------------------------------------------

    @staticmethod
    def add_adl(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        mfm = (
            (
                (df["close"] - df["low"])
                -
                (df["high"] - df["close"])
            )
            /
            (
                df["high"] -
                df["low"]
            ).replace(0, 1)
        )

        mfv = (
            mfm *
            df["volume"]
        )

        df["ADL"] = mfv.cumsum()

        return df

    # --------------------------------------------------
    # CMF
    # --------------------------------------------------

    @staticmethod
    def add_cmf(
        df: pd.DataFrame,
        length: int = 20,
    ) -> pd.DataFrame:

        mfm = (
            (
                (df["close"] - df["low"])
                -
                (df["high"] - df["close"])
            )
            /
            (
                df["high"] -
                df["low"]
            ).replace(0, 1)
        )

        mfv = (
            mfm *
            df["volume"]
        )

        df["CMF"] = (
            mfv.rolling(length).sum()
            /
            df["volume"]
            .rolling(length)
            .sum()
        )

        return df

    # --------------------------------------------------
    # Money Flow Index
    # --------------------------------------------------

    @staticmethod
    def add_mfi(
        df: pd.DataFrame,
        length: int = 14,
    ) -> pd.DataFrame:

        tp = (
            df["high"] +
            df["low"] +
            df["close"]
        ) / 3

        money_flow = (
            tp *
            df["volume"]
        )

        positive = money_flow.where(
            tp > tp.shift(),
            0,
        )

        negative = money_flow.where(
            tp < tp.shift(),
            0,
        )

        positive_sum = (
            positive
            .rolling(length)
            .sum()
        )

        negative_sum = (
            negative
            .rolling(length)
            .sum()
        )

        ratio = (
            positive_sum /
            negative_sum.replace(0, 1)
        )

        df["MFI"] = (
            100
            -
            (
                100 /
                (1 + ratio)
            )
        )

        return df

    # --------------------------------------------------
    # ALL
    # --------------------------------------------------

    @staticmethod
    def add_all(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        df = VolumeIndicators.add_volume_sma(df, 20)

        df = VolumeIndicators.add_volume_sma(df, 50)

        df = VolumeIndicators.add_rvol(df, 20)

        df = VolumeIndicators.add_vwap(df)

        df = VolumeIndicators.add_obv(df)

        df = VolumeIndicators.add_adl(df)

        df = VolumeIndicators.add_cmf(df)

        df = VolumeIndicators.add_mfi(df)

        return df