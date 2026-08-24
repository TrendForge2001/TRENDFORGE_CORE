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
from models.technical_snapshot import TechnicalSnapshot

logger = logging.getLogger(__name__)


class IndicatorEngine:
    """Single authoritative indicator engine with an explicit output contract."""

    REQUIRED_INPUTS = ("open", "high", "low", "close", "volume")
    REQUIRED_OUTPUTS = (
        "EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200",
        "VWMA_9", "VWMA_26", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST",
        "ADX", "+DI", "-DI", "ATR", "ATR_PERCENT", "BB_WIDTH",
        "VOL_SMA_20", "RVOL", "VWAP", "OBV", "CMF", "MFI",
        "BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND",
    )

    @classmethod
    def validate(cls, df: pd.DataFrame) -> None:
        if not isinstance(df, pd.DataFrame):
            raise TypeError("OHLCV data must be a pandas DataFrame")
        missing = sorted(set(cls.REQUIRED_INPUTS).difference(df.columns))
        if missing:
            raise ValueError(f"Missing columns: {missing}")
        if df.empty:
            raise ValueError("OHLCV dataframe is empty")
        if len(df) < 30:
            raise ValueError("Minimum 30 candles required for the scanner indicator contract")
        numeric = df[list(cls.REQUIRED_INPUTS)].apply(pd.to_numeric, errors="coerce")
        if numeric.isna().any().any():
            bad = [c for c in cls.REQUIRED_INPUTS if numeric[c].isna().any()]
            raise ValueError(f"Non-numeric/invalid OHLCV values: {bad}")
        if (numeric["volume"] < 0).any():
            raise ValueError("Volume cannot be negative")

    @classmethod
    def validate_output(cls, df: pd.DataFrame) -> None:
        missing = sorted(set(cls.REQUIRED_OUTPUTS).difference(df.columns))
        if missing:
            raise RuntimeError(f"Indicator pipeline missing required outputs: {missing}")
        if not df.empty:
            row = df.iloc[-1]
            # Boolean outputs are allowed to be NaN upstream, but must resolve to a bool.
            for key in ("BREAKOUT", "BREAKDOWN", "UPTREND", "DOWNTREND"):
                if pd.isna(row[key]):
                    raise RuntimeError(f"Indicator pipeline produced null flag: {key}")

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        self.validate(df)
        out = df.copy()
        for column in self.REQUIRED_INPUTS:
            out[column] = pd.to_numeric(out[column], errors="coerce")

        out = TrendIndicators.add_all_smas(out)
        out = TrendIndicators.add_all_emas(out)
        out["VWMA_9"] = VWMAIndicator(9).calculate(out)
        out["VWMA_26"] = VWMAIndicator(26).calculate(out)
        out = MomentumIndicators.add_all(out)
        out = VolatilityIndicators.add_all(out)
        out = VolumeIndicators.add_all(out)
        out = CandlestickPatterns.add_all(out)
        out = PriceAction.add_all(out)
        self.validate_output(out)
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
            "close": row.get("close"), "ema9": row.get("EMA_9"),
            "ema20": row.get("EMA_20"), "ema50": row.get("EMA_50"),
            "ema100": row.get("EMA_100"), "ema200": row.get("EMA_200"),
            "vwma9": row.get("VWMA_9"), "vwma26": row.get("VWMA_26"),
            "rsi": row.get("RSI"), "macd": row.get("MACD"),
            "macd_signal": row.get("MACD_SIGNAL"), "adx": row.get("ADX"),
            "atr": row.get("ATR"), "rvol": row.get("RVOL"), "vwap": row.get("VWAP"),
            "cmf": row.get("CMF"), "breakout": row.get("BREAKOUT"),
            "breakdown": row.get("BREAKDOWN"), "uptrend": row.get("UPTREND"),
            "downtrend": row.get("DOWNTREND"),
        }

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        try:
            value = float(value)
            return value if math.isfinite(value) else default
        except (TypeError, ValueError):
            return default

    def build_snapshot(self, symbol: str, timeframe: str, df: pd.DataFrame) -> TechnicalSnapshot:
        data = self.calculate(df)
        row = data.iloc[-1]
        return TechnicalSnapshot(
            symbol=symbol, timeframe=timeframe,
            open=self._safe_float(row["open"]), high=self._safe_float(row["high"]),
            low=self._safe_float(row["low"]), close=self._safe_float(row["close"]),
            volume=self._safe_float(row["volume"]),
            ema9=self._safe_float(row.get("EMA_9")), ema20=self._safe_float(row.get("EMA_20")),
            ema50=self._safe_float(row.get("EMA_50")), ema100=self._safe_float(row.get("EMA_100")),
            ema200=self._safe_float(row.get("EMA_200")), vwma9=self._safe_float(row.get("VWMA_9")),
            vwma26=self._safe_float(row.get("VWMA_26")), vwap=self._safe_float(row.get("VWAP")),
            rsi=self._safe_float(row.get("RSI")), macd=self._safe_float(row.get("MACD")),
            macd_signal=self._safe_float(row.get("MACD_SIGNAL")),
            macd_histogram=self._safe_float(row.get("MACD_HIST")),
            adx=self._safe_float(row.get("ADX")), plus_di=self._safe_float(row.get("+DI")),
            minus_di=self._safe_float(row.get("-DI")), atr=self._safe_float(row.get("ATR")),
            obv=self._safe_float(row.get("OBV")), cmf=self._safe_float(row.get("CMF")),
            bb_upper=self._safe_float(row.get("BB_UPPER")), bb_middle=self._safe_float(row.get("BB_MID")),
            bb_lower=self._safe_float(row.get("BB_LOWER")),
        )

    def health(self) -> dict:
        return {
            "status": "healthy", "ema": [9, 20, 50, 100, 200], "vwma": [9, 26],
            "momentum": True, "volatility": True, "volume": True,
            "candlestick": True, "price_action": True,
            "required_output_count": len(self.REQUIRED_OUTPUTS),
        }
