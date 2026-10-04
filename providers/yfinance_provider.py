"""Yahoo Finance fallback provider for TrendForge."""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any

from .market_data_provider import MarketDataProvider

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


class YahooFinanceProvider(MarketDataProvider):
    _instance: "YahooFinanceProvider | None" = None
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

    def health(self) -> dict[str, Any]:
        """Report local provider readiness without making a network request."""
        return {
            "status": "configured",
            "provider": self.__class__.__name__,
            "network_probe": False,
        }

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

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
            return symbol
        return f"{symbol}.NS"

    def ticker(self, symbol: str):
        return yf.Ticker(self.normalize_symbol(symbol))

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

    @retry
    def download(self, symbols: list[str], period="6mo", interval="1d") -> pd.DataFrame:
        normalized = [self.normalize_symbol(s) for s in symbols]
        return yf.download(normalized, period=period, interval=interval, group_by="ticker", threads=True, progress=False)

    @retry
    def live_price(self, symbol):
        info = self.ticker(symbol).fast_info
        return {"symbol": symbol, "last_price": info.get("lastPrice"), "open": info.get("open"), "high": info.get("dayHigh"), "low": info.get("dayLow"), "volume": info.get("lastVolume")}

    def company_info(self, symbol): return self.ticker(symbol).info
    def financials(self, symbol): return self.ticker(symbol).financials
    def quarterly_financials(self, symbol): return self.ticker(symbol).quarterly_financials
    def balance_sheet(self, symbol): return self.ticker(symbol).balance_sheet
    def quarterly_balance_sheet(self, symbol): return self.ticker(symbol).quarterly_balance_sheet
    def cashflow(self, symbol): return self.ticker(symbol).cashflow
    def quarterly_cashflow(self, symbol): return self.ticker(symbol).quarterly_cashflow
    def earnings(self, symbol): return self.ticker(symbol).earnings
    def quarterly_earnings(self, symbol): return self.ticker(symbol).quarterly_earnings
    def dividends(self, symbol): return self.ticker(symbol).dividends
    def splits(self, symbol): return self.ticker(symbol).splits
    def insider_transactions(self, symbol): return self.ticker(symbol).insider_transactions
    def recommendations(self, symbol): return self.ticker(symbol).recommendations
    def sustainability(self, symbol): return self.ticker(symbol).sustainability
    def option_expiries(self, symbol): return self.ticker(symbol).options
    def option_chain(self, symbol, expiry): return self.ticker(symbol).option_chain(expiry)
    def news(self, symbol): return self.ticker(symbol).news
    def major_holders(self, symbol): return self.ticker(symbol).major_holders
    def institutional_holders(self, symbol): return self.ticker(symbol).institutional_holders
    def mutualfund_holders(self, symbol): return self.ticker(symbol).mutualfund_holders
    def nifty50(self): return self.historical_data("^NSEI")
    def banknifty(self): return self.historical_data("^NSEBANK")
    def sensex(self): return self.historical_data("^BSESN")
    def india_vix(self): return self.historical_data("^INDIAVIX")

    def ping(self):
        try:
            self.live_price("RELIANCE")
            return True
        except Exception:
            return False


YFinanceProvider = YahooFinanceProvider

yfinance_provider = YahooFinanceProvider()

__all__ = ["YahooFinanceProvider", "YFinanceProvider", "yfinance_provider"]
