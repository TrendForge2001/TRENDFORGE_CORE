"""
TrendForge v2
Momentum Indicators
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

CALCULATION_VERSION = "rolling-v2-adx-dm-ties"


class MomentumIndicators:
    """
    Momentum Indicators

    RSI
    MACD
    ROC
    Momentum
    ADX
    """

    # --------------------------------------------------
    # RSI
    # --------------------------------------------------

    @staticmethod
    def add_rsi(
        df: pd.DataFrame,
        length: int = 14,
        column: str | None = None,
    ) -> pd.DataFrame:
        delta = df["close"].diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(length).mean()
        avg_loss = loss.rolling(length).mean()
        rs = avg_gain / avg_loss
        values = 100 - (100 / (1 + rs))
        key = column or ("RSI" if length == 14 else f"RSI_{length}")
        df[key] = values
        if length == 14:
            df["RSI"] = values
            df["RSI_14"] = values
        return df

    # --------------------------------------------------
    # EMA Helper
    # --------------------------------------------------

    @staticmethod
    def _ema(
        series,
        length,
    ):

        return series.ewm(
            span=length,
            adjust=False,
        ).mean()

    # --------------------------------------------------
    # MACD
    # --------------------------------------------------

    @staticmethod
    def add_macd(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        ema12 = MomentumIndicators._ema(
            df["close"],
            12,
        )

        ema26 = MomentumIndicators._ema(
            df["close"],
            26,
        )

        df["MACD"] = ema12 - ema26

        df["MACD_SIGNAL"] = (
            MomentumIndicators._ema(
                df["MACD"],
                9,
            )
        )

        df["MACD_HIST"] = (
            df["MACD"]
            - df["MACD_SIGNAL"]
        )

        return df

    # --------------------------------------------------
    # ROC
    # --------------------------------------------------

    @staticmethod
    def add_roc(
        df: pd.DataFrame,
        length: int = 12,
    ) -> pd.DataFrame:

        df["ROC"] = (
            df["close"]
            .pct_change(length)
            * 100
        )

        return df

    # --------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------

    @staticmethod
    def add_momentum(
        df: pd.DataFrame,
        length: int = 10,
    ) -> pd.DataFrame:

        df["MOMENTUM"] = (
            df["close"]
            - df["close"].shift(length)
        )

        return df

    # --------------------------------------------------
    # ADX
    # --------------------------------------------------

    @staticmethod
    def add_adx(
        df: pd.DataFrame,
        length: int = 14,
    ) -> pd.DataFrame:

        high = df["high"]

        low = df["low"]

        close = df["close"]

        up_move = high.diff()
        down_move = -low.diff()

        # Compare both legs against the original movement. Equal positive
        # movements cancel; filtering one leg first would bias ties bearish.
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        tr = pd.concat(
            [
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)

        atr = tr.rolling(length).mean()

        plus_di = (
            100
            * plus_dm.rolling(length).mean()
            / atr
        )

        minus_di = (
            100
            * minus_dm.rolling(length).mean()
            / atr
        )

        dx = (
            (
                (plus_di - minus_di).abs()
                /
                (plus_di + minus_di)
            )
            * 100
        )

        df["ADX"] = dx.rolling(length).mean()

        df["+DI"] = plus_di

        df["-DI"] = minus_di

        return df

    # --------------------------------------------------
    # ALL
    # --------------------------------------------------

    @staticmethod
    def add_all(
        df: pd.DataFrame,
    ) -> pd.DataFrame:

        df = MomentumIndicators.add_rsi(df, 14)

        df = MomentumIndicators.add_rsi(df, 20, column="RSI_20")

        df["RSI_SMOOTH_14"] = df["RSI_14"].rolling(14).mean()

        df = MomentumIndicators.add_macd(df)

        df = MomentumIndicators.add_roc(df)

        df = MomentumIndicators.add_momentum(df)

        df = MomentumIndicators.add_adx(df)

        return df
