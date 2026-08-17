"""Canonical TrendForge technical-indicator pipeline."""
from __future__ import annotations

import logging
import pandas as pd

from indicators.trend import TrendIndicators
from indicators.momentum import MomentumIndicators
from indicators.volatility import VolatilityIndicators
from indicators.volume import VolumeIndicators
from indicators.candlestick import CandlestickPatterns
from indicators.price_action import PriceAction
from indicators.vwma import VWMAIndicator
from models.technical_snapshot import TechnicalSnapshot

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Single authoritative indicator engine.

    Preserves EMA 9/20/50/100/200 and VWMA 9/26 while retaining the existing
    momentum, volatility, volume, candlestick and price-action pipelines.
    """

    @staticmethod
    def validate(df: pd.DataFrame) -> None:
        required = {"open", "high", "low", "close", "volume"}
        missing = sorted(required.difference(df.columns))
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if df.empty:
            raise ValueError("OHLCV dataframe is empty")

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate(df)
        out = df.copy()
        out = TrendIndicators.add_all_smas(out)
        out = TrendIndicators.add_all_emas(out)
        out["VWMA_9"] = VWMAIndicator(9).calculate(out)
        out["VWMA_26"] = VWMAIndicator(26).calculate(out)
        out = MomentumIndicators.add_all(out)
        out = VolatilityIndicators.add_all(out)
        out = VolumeIndicators.add_all(out)
        out = CandlestickPatterns.add_all(out)
        out = PriceAction.add_all(out)
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
            "close": row.get("close"),
            "ema9": row.get("EMA_9"),
            "ema20": row.get("EMA_20"),
            "ema50": row.get("EMA_50"),
            "ema100": row.get("EMA_100"),
            "ema200": row.get("EMA_200"),
            "vwma9": row.get("VWMA_9"),
            "vwma26": row.get("VWMA_26"),
            "rsi": row.get("RSI"),
            "macd": row.get("MACD"),
            "macd_signal": row.get("MACD_SIGNAL"),
            "adx": row.get("ADX"),
            "atr": row.get("ATR"),
            "rvol": row.get("RVOL"),
            "vwap": row.get("VWAP"),
            "cmf": row.get("CMF"),
            "breakout": row.get("BREAKOUT"),
            "breakdown": row.get("BREAKDOWN"),
            "uptrend": row.get("UPTREND"),
            "downtrend": row.get("DOWNTREND"),
        }

    def build_snapshot(self, symbol: str, timeframe: str, df: pd.DataFrame) -> TechnicalSnapshot:
        data = self.calculate(df)
        row = data.iloc[-1]
        return TechnicalSnapshot(
            symbol=symbol, timeframe=timeframe,
            open=float(row["open"]), high=float(row["high"]), low=float(row["low"]),
            close=float(row["close"]), volume=float(row["volume"]),
            ema9=float(row.get("EMA_9", 0)), ema20=float(row.get("EMA_20", 0)),
            ema50=float(row.get("EMA_50", 0)), ema100=float(row.get("EMA_100", 0)),
            ema200=float(row.get("EMA_200", 0)), vwma9=float(row.get("VWMA_9", 0)),
            vwma26=float(row.get("VWMA_26", 0)), vwap=float(row.get("VWAP", 0) or 0),
            rsi=float(row.get("RSI", 0) or 0), macd=float(row.get("MACD", 0) or 0),
            macd_signal=float(row.get("MACD_SIGNAL", 0) or 0),
            macd_histogram=float(row.get("MACD_HIST", 0) or 0),
            adx=float(row.get("ADX", 0) or 0), plus_di=float(row.get("+DI", 0) or 0),
            minus_di=float(row.get("-DI", 0) or 0), atr=float(row.get("ATR", 0) or 0),
            obv=float(row.get("OBV", 0) or 0), cmf=float(row.get("CMF", 0) or 0),
            bb_upper=float(row.get("BB_UPPER", 0) or 0), bb_middle=float(row.get("BB_MID", 0) or 0),
            bb_lower=float(row.get("BB_LOWER", 0) or 0),
        )

    def health(self) -> dict:
        return {"status": "healthy", "ema": [9, 20, 50, 100, 200], "vwma": [9, 26],
                "momentum": True, "volatility": True, "volume": True,
                "candlestick": True, "price_action": True}
