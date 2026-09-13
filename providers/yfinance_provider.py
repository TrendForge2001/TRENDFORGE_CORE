"""Yahoo Finance fallback provider for TrendForge."""

from __future__ import annotations
import threading
import time
from functools import wraps
from typing import Any
import pandas as pd
import yfinance as yf


class YFinanceProvider:
    _instance = None
    _lock = threading.Lock()
    CACHE_TTL = 60

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self.cache = {}
        self._initialized = True

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        symbol = str(symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
            return symbol
        return f"{symbol}.NS"

    @staticmethod
    def retry(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = 1
            for attempt in range(3):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(delay)
                    delay *= 2
        return wrapper

    def ticker(self, symbol: str):
        return yf.Ticker(self.normalize_symbol(symbol))

    def candles(self, symbol, period="6mo", interval="1d"):
        return self.historical_data(symbol, period=period, interval=interval, auto_adjust=False)

    @retry
    def historical_data(self, symbol: str, period="1y", interval="1d", auto_adjust=True) -> pd.DataFrame:
        key = ("history", self.normalize_symbol(symbol), period, interval, auto_adjust)
        item = self.cache.get(key)
        if item and time.time() - item[1] <= self.CACHE_TTL:
            return item[0].copy()
        data = self.ticker(symbol).history(period=period, interval=interval, auto_adjust=auto_adjust)
        if not isinstance(data, pd.DataFrame):
            raise TypeError("Yahoo Finance returned non-tabular market data")
        self.cache[key] = (data.copy(), time.time())
        return data

    @retry
    def live_price(self, symbol):
        info = self.ticker(symbol).fast_info
        return {"symbol": str(symbol).upper(), "last_price": info.get("lastPrice"), "open": info.get("open"), "high": info.get("dayHigh"), "low": info.get("dayLow"), "volume": info.get("lastVolume")}

    def health(self):
        return {"status": "configured", "provider": self.__class__.__name__}

    def ping(self):
        try:
            return self.live_price("RELIANCE").get("last_price") is not None
        except Exception:
            return False


YahooFinanceProvider = YFinanceProvider
yfinance_provider = YFinanceProvider()
__all__ = ["YFinanceProvider", "YahooFinanceProvider", "yfinance_provider"]
