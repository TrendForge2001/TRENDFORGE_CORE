"""Yahoo Finance fallback provider for TrendForge."""
from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any

import pandas as pd
import yfinance as yf

from .market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
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
        self.cache: dict[Any, tuple[Any, float]] = {}
        self._initialized = True

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
            return symbol
        return f"{symbol}.NS"

    def ticker(self, symbol: str):
        return yf.Ticker(self.normalize_symbol(symbol))

    def _cache_get(self, key):
        item = self.cache.get(key)
        if item is None:
            return None
        value, timestamp = item
        if time.time() - timestamp > self.CACHE_TTL:
            self.cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key, value):
        self.cache[key] = (value, time.time())

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

    @retry
    def historical_data(self, symbol: str, period="1y", interval="1d", auto_adjust=True) -> pd.DataFrame:
        key = ("history", symbol, period, interval, auto_adjust)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        data = self.ticker(symbol).history(period=period, interval=interval, auto_adjust=auto_adjust)
        self._cache_set(key, data)
        return data

    def candles(self, symbol, period="6mo", interval="1d"):
        return self.historical_data(symbol, period=period, interval=interval, auto_adjust=False)

    def live_price(self, symbol):
        info = self.ticker(symbol).fast_info
        return {"symbol": symbol, "last_price": info.get("lastPrice"),
                "open": info.get("open"), "high": info.get("dayHigh"),
                "low": info.get("dayLow"), "volume": info.get("lastVolume")}

    def __getattr__(self, name):
        ticker = getattr(self, "ticker", None)
        if callable(ticker):
            return getattr(ticker, name)
        raise AttributeError(name)

    def health(self):
        return {"status": "configured", "provider": self.__class__.__name__}


yfinance_provider = YahooFinanceProvider()
YFinanceProvider = YahooFinanceProvider
__all__ = ["YahooFinanceProvider", "YFinanceProvider", "yfinance_provider"]
