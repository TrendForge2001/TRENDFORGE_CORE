"""Kite-specific historical OHLCV adapter.

Keeps Zerodha instrument-token/date-range mechanics out of the scanner layer.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from database.repositories.instrument_repository import InstrumentRepository
from providers.kite_provider import KiteProvider


class KiteHistoricalAdapter:
    def __init__(
        self,
        provider: KiteProvider | None = None,
        instruments: InstrumentRepository | None = None,
    ) -> None:
        self.provider = provider or KiteProvider()
        self.instruments = instruments or InstrumentRepository()

    def token_for(self, symbol: str) -> int:
        token = self.instruments.token(symbol.upper())
        if token is None:
            raise KeyError(f"No Kite instrument token for {symbol}")
        return int(token)

    @staticmethod
    def _date_range(period: str) -> tuple[date, date]:
        end = date.today()
        periods = {"1d": 1, "5d": 5, "1mo": 31, "3mo": 93, "6mo": 186, "1y": 366}
        days = periods.get(period, 366)
        return end - timedelta(days=days), end

    @staticmethod
    def _normalize(rows: Any) -> pd.DataFrame:
        frame = pd.DataFrame(rows)
        if frame.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"])
            frame = frame.set_index("date")
        frame.columns = [str(c).lower() for c in frame.columns]
        required = ["open", "high", "low", "close", "volume"]
        for column in required:
            if column not in frame.columns:
                frame[column] = 0.0
        return frame[required].apply(pd.to_numeric, errors="coerce").dropna(subset=["close"])

    def candles(self, symbol: str, period: str = "6mo", interval: str = "day") -> pd.DataFrame:
        token = self.token_for(symbol)
        start, end = self._date_range(period)
        rows = self.provider.safe_historical(token, start, end, interval)
        return self._normalize(rows)


__all__ = ["KiteHistoricalAdapter"]
