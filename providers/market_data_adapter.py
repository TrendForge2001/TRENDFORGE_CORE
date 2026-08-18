"""Canonical market-data adapter for TrendForge scanner consumers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from .market_data_provider import MarketDataProvider


class MarketDataAdapter(MarketDataProvider):
    """Normalize provider output into the canonical OHLCV contract."""

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
            result.columns = [
                "_".join(str(part) for part in column if str(part).strip())
                if isinstance(column, tuple) else str(column)
                for column in result.columns
            ]
        result.columns = [str(column).strip().lower().replace(" ", "_") for column in result.columns]
        return result

    def candles(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required")

        if callable(getattr(self.provider, "historical_data", None)):
            frame = self.provider.historical_data(symbol, period=period, interval=interval, auto_adjust=False)
        elif callable(getattr(self.provider, "candles", None)):
            frame = self.provider.candles(symbol, period=period, interval=interval)
        else:
            raise AttributeError("Provider must implement historical_data() or candles()")

        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"Provider returned no candle data for {symbol}")

        frame = self._flatten_columns(frame)
        missing = [column for column in self.REQUIRED if column not in frame.columns]
        if missing:
            raise ValueError(f"Provider returned incomplete OHLCV data for {symbol}: {missing}")

        result = frame.loc[:, list(self.REQUIRED)].copy()
        for column in self.REQUIRED:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(subset=list(self.REQUIRED))
        if result.empty:
            raise ValueError(f"Provider returned no valid OHLCV rows for {symbol}")
        return result

    def batch_candles(self, symbols: list[str], period: str = "1y", interval: str = "1d") -> dict[str, pd.DataFrame]:
        """Fetch symbols concurrently; failed symbols are reported separately."""
        results, failures = self.batch_candles_with_errors(symbols, period, interval)
        self.last_batch_errors = failures
        return results

    def batch_candles_with_errors(self, symbols: list[str], period: str = "1y", interval: str = "1d") -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        normalized = []
        seen = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        if not normalized:
            return {}, {}

        results: dict[str, pd.DataFrame] = {}
        failures: dict[str, str] = {}
        workers = min(self.max_workers, len(normalized))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trendforge-data") as executor:
            futures = {executor.submit(self.candles, symbol, period, interval): symbol for symbol in normalized}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    failures[symbol] = str(exc)
        return results, failures

    def health(self) -> dict[str, Any]:
        return {"status": "configured", "provider": self.provider.__class__.__name__, "max_workers": self.max_workers}


__all__ = ["MarketDataAdapter"]
