"""Canonical market-data adapter for TrendForge scanner consumers."""

from __future__ import annotations

from typing import Any

import pandas as pd


class MarketDataAdapter:
    """Normalize provider output into the OHLCV contract expected by TrendForge."""

    REQUIRED = ("open", "high", "low", "close", "volume")

    def __init__(self, provider: Any):
        self.provider = provider

    @staticmethod
    def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if isinstance(result.columns, pd.MultiIndex):
            result.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in result.columns]
        result.columns = [str(c).strip().lower().replace(" ", "_") for c in result.columns]
        return result

    def candles(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        if hasattr(self.provider, "historical_data"):
            frame = self.provider.historical_data(symbol, period=period, interval=interval, auto_adjust=False)
        elif hasattr(self.provider, "candles"):
            frame = self.provider.candles(symbol, period=period, interval=interval)
        else:
            raise AttributeError("Provider must implement historical_data() or candles()")

        if frame is None:
            return pd.DataFrame(columns=self.REQUIRED)
        frame = self._flatten_columns(frame)
        missing = [column for column in self.REQUIRED if column not in frame.columns]
        if missing:
            raise ValueError(f"Provider returned incomplete OHLCV data: {missing}")
        return frame.loc[:, list(self.REQUIRED)].copy()

    def batch_candles(self, symbols: list[str], period: str = "1y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        return {symbol: self.candles(symbol, period=period, interval=interval) for symbol in symbols}

    def health(self) -> dict[str, Any]:
        return {"status": "configured", "provider": self.provider.__class__.__name__}


__all__ = ["MarketDataAdapter"]
