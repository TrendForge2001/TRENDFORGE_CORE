"""Canonical TrendForge technical-indicator pipeline."""
from __future__ import annotations

import logging
import math
import pandas as pd

from indicators.trend import TrendIndicators
from indicators.momentum import MomentumIndicators
from indicators.volatility import VolatilityIndicators
from indicators.volume import VolumeIndicators
from indicators.candlestick import CandlestickPatterns
from indicators.price_action import PriceAction
from indicators.vwma import VWMAIndicator
from indicators.pivots import FibonacciPivots
from models.technical_snapshot import TechnicalSnapshot

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Single authoritative indicator engine.

    Preserves EMA 9/20/50/100/200 and VWMA 9/26 while retaining the existing
    momentum, volatility, volume, candlestick and price-action pipelines.
    """

    MIN_CANDLES = 30
    REQUIRED_OUTPUTS = frozenset({
        "EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200",
        "VWMA_9", "VWMA_26", "VWMA_50", "VWMA_100",
        "VWAP", "VWAP_SESSION", "LOW_20_PREV", "RSI", "RSI_14", "RSI_20", "RSI_SMOOTH_14",
        "MACD", "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI",
        "ATR", "OBV", "CMF", "VOL_SMA_20", "VOL_SMA_50",
        "BB_UPPER", "BB_MID", "BB_LOWER",
        "SUPERTREND_10_3", "SUPERTREND_DIR",
        "FIB_PIVOT", "FIB_R1", "FIB_R2", "FIB_R3",
        "FIB_S1", "FIB_S2", "FIB_S3",
        "HIGH_252", "LOW_252", "DIST_52W_HIGH_PCT",
    })

    @classmethod
    def validate(cls, df: pd.DataFrame) -> None:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("OHLCV data must be a pandas DataFrame")
        required = {"open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if df.empty:
            raise ValueError("OHLCV dataframe is empty")
        if len(df) < cls.MIN_CANDLES:
            raise ValueError(f"Minimum {cls.MIN_CANDLES} candles required")

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate(df)
        out = df.copy()
        out = TrendIndicators.add_all_smas(out)
        out = TrendIndicators.add_all_emas(out)
        out["VWMA_9"] = VWMAIndicator(9).calculate(out)
        out["VWMA_26"] = VWMAIndicator(26).calculate(out)
        out["VWMA_50"] = VWMAIndicator(50).calculate(out)
        out["VWMA_100"] = VWMAIndicator(100).calculate(out)
        out = TrendIndicators.add_supertrend(out, 10, 3.0)
        out = MomentumIndicators.add_all(out)
        out = VolatilityIndicators.add_all(out)
        out = VolumeIndicators.add_all(out)
        out = CandlestickPatterns.add_all(out)
        out = PriceAction.add_all(out)
        out = FibonacciPivots.add_all(out)
        return out

    @staticmethod
    def latest(df: pd.DataFrame) -> dict:
        if df.empty:
            raise ValueError("Cannot get latest candle from empty dataframe")
        return df.iloc[-1].to_dict()

    @staticmethod
    def summary(df: pd.DataFrame) -> dict:
        row = df.iloc[-1]
        return {
            "close": row.get("close"), "ema9": row.get("EMA_9"), "ema20": row.get("EMA_20"),
            "ema50": row.get("EMA_50"), "ema100": row.get("EMA_100"), "ema200": row.get("EMA_200"),
            "vwma9": row.get("VWMA_9"), "vwma26": row.get("VWMA_26"),
            "vwma50": row.get("VWMA_50"), "vwma100": row.get("VWMA_100"),
            "rsi": row.get("RSI"), "rsi20": row.get("RSI_20"),
            "supertrend": row.get("SUPERTREND_10_3"),
            "supertrend_dir": row.get("SUPERTREND_DIR"),
            "macd": row.get("MACD"), "macd_signal": row.get("MACD_SIGNAL"), "adx": row.get("ADX"),
            "atr": row.get("ATR"), "rvol": row.get("RVOL"), "vwap": row.get("VWAP"),
            "cmf": row.get("CMF"), "breakout": row.get("BREAKOUT"), "breakdown": row.get("BREAKDOWN"),
            "uptrend": row.get("UPTREND"), "downtrend": row.get("DOWNTREND"),
        }

    @staticmethod
    def _finite(row: pd.Series, key: str) -> float:
        value = row.get(key)
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"Latest indicator {key} is not numeric") from None
        if not math.isfinite(value):
            raise ValueError(f"Latest indicator {key} is not finite")
        return value

    def build_snapshot(self, symbol: str, timeframe: str, df: pd.DataFrame) -> TechnicalSnapshot:
        required = {"EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200", "VWMA_9", "VWMA_26",
                    "VWAP", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI",
                    "ATR", "OBV", "CMF", "BB_UPPER", "BB_MID", "BB_LOWER"}
        data = df.copy() if required.issubset(df.columns) else self.calculate(df)
        row = data.iloc[-1]
        values = {key: self._finite(row, key) for key in (
            "open", "high", "low", "close", "volume", "EMA_9", "EMA_20", "EMA_50",
            "EMA_100", "EMA_200", "VWMA_9", "VWMA_26", "VWAP", "RSI", "MACD",
            "MACD_SIGNAL", "MACD_HIST", "ADX", "+DI", "-DI", "ATR", "OBV", "CMF",
            "BB_UPPER", "BB_MID", "BB_LOWER")}
        return TechnicalSnapshot(
            symbol=symbol, timeframe=timeframe,
            open=values["open"], high=values["high"], low=values["low"], close=values["close"],
            volume=values["volume"], ema9=values["EMA_9"], ema20=values["EMA_20"],
            ema50=values["EMA_50"], ema100=values["EMA_100"], ema200=values["EMA_200"],
            vwma9=values["VWMA_9"], vwma26=values["VWMA_26"], vwap=values["VWAP"],
            rsi=values["RSI"], macd=values["MACD"], macd_signal=values["MACD_SIGNAL"],
            macd_histogram=values["MACD_HIST"], adx=values["ADX"], plus_di=values["+DI"],
            minus_di=values["-DI"], atr=values["ATR"], obv=values["OBV"], cmf=values["CMF"],
            bb_upper=values["BB_UPPER"], bb_middle=values["BB_MID"], bb_lower=values["BB_LOWER"],
        )

    def health(self) -> dict:
        return {
            "status": "healthy",
            "version": "R72.5.1",
            "min_candles": self.MIN_CANDLES,
            "ema": [9, 20, 50, 100, 200],
            "vwma": [9, 26],
            "vwma_extended": [9, 26, 50, 100],
            "rsi": [14, 20],
            "smoothed_rsi": [14],
            "supertrend": {"length": 10, "multiplier": 3.0},
            "volume_ma": [20, 50],
            "fibonacci_pivots": True,
            "rolling_52week_context": True,
            "momentum": True,
            "volatility": True,
            "volume": True,
            "candlestick": True,
            "price_action": True,
        }
