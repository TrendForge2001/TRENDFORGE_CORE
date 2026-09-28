"""Canonical market-data adapter for TrendForge scanner consumers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import pandas as pd

from .market_data_provider import MarketDataProvider


class MarketDataAdapter(MarketDataProvider):
    REQUIRED = ("open", "high", "low", "close", "volume")

    def __init__(self, provider: Any, max_workers: int = 8):
        if provider is None:
            raise ValueError("A market-data provider is required")
        self.provider = provider
        self.max_workers = max(1, int(max_workers))
        self.last_batch_errors: dict[str, str] = {}

    @staticmethod
    def _flatten_columns(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        if isinstance(result.columns, pd.MultiIndex):
            flattened = []
            for column in result.columns:
                parts = [str(part).strip() for part in column if str(part).strip()]
                lowered = [part.lower().replace(" ", "_") for part in parts]
                if lowered and lowered[0] in {"open", "high", "low", "close", "volume"}:
                    flattened.append(lowered[0])
                elif lowered and lowered[-1] in {"open", "high", "low", "close", "volume"}:
                    flattened.append(lowered[-1])
                else:
                    flattened.append("_".join(lowered))
            result.columns = flattened
        result.columns = [str(column).strip().lower().replace(" ", "_") for column in result.columns]
        return result

    @classmethod
    def _normalize(cls, symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(f"Provider returned no candle data for {symbol}")
        frame = cls._flatten_columns(frame)
        missing = [column for column in cls.REQUIRED if column not in frame.columns]
        if missing:
            raise ValueError(f"Provider returned incomplete OHLCV data for {symbol}: {missing}")
        result = frame.loc[:, list(cls.REQUIRED)].copy()
        for column in cls.REQUIRED:
            result[column] = pd.to_numeric(result[column], errors="coerce")
        result = result.dropna(subset=list(cls.REQUIRED))
        if result.empty:
            raise ValueError(f"Provider returned no valid OHLCV rows for {symbol}")
        return result

    def candles(self, symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required")
        historical = getattr(self.provider, "historical_data", None)
        candles = getattr(self.provider, "candles", None)
        if callable(candles):
            frame = candles(symbol, period=period, interval=interval)
        elif callable(historical):
            frame = historical(symbol, period=period, interval=interval, auto_adjust=False)
        else:
            raise AttributeError("Provider must implement historical_data() or candles()")
        return self._normalize(symbol, frame)

    def batch_candles(self, symbols: list[str], period="1y", interval="1d"):
        results, failures = self.batch_candles_with_errors(symbols, period, interval)
        self.last_batch_errors = failures
        return results

    def batch_candles_with_errors(self, symbols, period="1y", interval="1d"):
        normalized, seen = [], set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)
        if not normalized:
            return {}, {}
        results, failures = {}, {}
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

    def health(self):
        provider_health = {}
        health = getattr(self.provider, "health", None)
        if callable(health):
            try:
                provider_health = health()
            except Exception as exc:
                provider_health = {"status": "degraded", "error": str(exc)}
        return {
            "status": "configured",
            "provider": self.provider.__class__.__name__,
            "provider_health": provider_health,
            "max_workers": self.max_workers,
        }


__all__ = ["MarketDataAdapter"]
