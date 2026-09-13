"""Canonical market-data adapter for TrendForge scanner consumers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
import pandas as pd


class MarketDataAdapter:
    REQUIRED = ("open", "high", "low", "close", "volume")

    def __init__(self, provider: Any, max_workers: int = 8):
        if provider is None:
            raise ValueError("A market-data provider is required")
        self.provider = provider
        self.max_workers = max(1, int(max_workers))

    @staticmethod
    def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if isinstance(result.columns, pd.MultiIndex):
            result.columns = [str(c[0]) for c in result.columns]
        result.columns = [str(c).strip().lower().replace(" ", "_") for c in result.columns]
        return result

    def candles(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        if hasattr(self.provider, "candles"):
            frame = self.provider.candles(symbol, period=period, interval=interval)
        elif hasattr(self.provider, "historical_data"):
            frame = self.provider.historical_data(symbol, period=period, interval=interval, auto_adjust=False)
        else:
            raise AttributeError("Provider must implement candles() or historical_data()")
        if frame is None:
            return pd.DataFrame(columns=self.REQUIRED)
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Provider must return a pandas DataFrame")
        frame = self._flatten_columns(frame)
        missing = [column for column in self.REQUIRED if column not in frame.columns]
        if missing:
            raise ValueError(f"Provider returned incomplete OHLCV data: {missing}")
        result = frame.loc[:, list(self.REQUIRED)].copy()
        for column in self.REQUIRED:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        return result.dropna(subset=["open", "high", "low", "close"])

    def batch_candles(self, symbols, period: str = "1y", interval: str = "1d"):
        symbols = list(dict.fromkeys(str(s).strip().upper() for s in symbols if str(s).strip()))
        if not symbols:
            return {}
        results = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(symbols))) as executor:
            futures = {executor.submit(self.candles, s, period, interval): s for s in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception:
                    continue
        return results

    def health(self):
        return {"status": "configured", "provider": self.provider.__class__.__name__, "max_workers": self.max_workers}
