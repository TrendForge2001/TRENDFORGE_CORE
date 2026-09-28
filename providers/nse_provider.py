"""Centralized NSE market-data provider with caching and retries."""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)


class NSEProvider:
    _instance = None
    _lock = threading.Lock()
    BASE_URL = "https://www.nseindia.com"
    CACHE_TTL = 60
    HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9", "Accept": "application/json,text/plain,*/*", "Referer": "https://www.nseindia.com/"}

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        self.cache = {}
        self._initialize_session()
        self._initialized = True

    def _initialize_session(self):
        try:
            self.session.get(self.BASE_URL, timeout=10)
        except requests.RequestException as exc:
            logger.warning("NSE session initialization failed: %s", exc)

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
    def _get(self, endpoint, params=None):
        key = (endpoint, tuple(sorted((params or {}).items())))
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        response = self.session.get(f"{self.BASE_URL}{endpoint}", params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        self._cache_set(key, data)
        return data

    def market_status(self): return self._get("/api/marketStatus")
    def index_quote(self, index_name): return self._get("/api/allIndices", {"index": index_name})
    def equity_quote(self, symbol): return self._get("/api/quote-equity", {"symbol": symbol})
    def quote(self, symbol): return self.equity_quote(symbol)
    def option_chain(self, symbol): return self._get("/api/option-chain-equities", {"symbol": symbol})
    def market_breadth(self): return self._get("/api/equity-stockIndices", {"index": "NIFTY 50"})
    def top_gainers(self): return self._get("/api/live-analysis-variations", {"index": "gainers"})
    def top_losers(self): return self._get("/api/live-analysis-variations", {"index": "losers"})
    def most_active(self): return self._get("/api/live-analysis-most-active-securities")
    def fii_dii(self): return self._get("/api/fiiDiiTradeReact")
    def holidays(self): return self._get("/api/holiday-master", {"type": "trading"})
    def circulars(self): return self._get("/api/circulars")
    def corporate_actions(self): return self._get("/api/corporates-corporateActions")
    def bulk_deals(self): return self._get("/api/historicalOR/bulk-deals")
    def block_deals(self): return self._get("/api/historicalOR/block-deals")
    def bhavcopy(self): return self._get("/api/reports", {"archives": "downloads"})

    def advance_decline(self):
        advances = declines = unchanged = 0
        for stock in self.market_breadth().get("data", []):
            change = stock.get("change", 0) or 0
            if change > 0: advances += 1
            elif change < 0: declines += 1
            else: unchanged += 1
        return {"advances": advances, "declines": declines, "unchanged": unchanged}

    def nifty50(self): return self.index_quote("NIFTY 50")
    def banknifty(self): return self.index_quote("NIFTY BANK")
    def finnifty(self): return self.index_quote("NIFTY FINANCIAL SERVICES")
    def midcap(self): return self.index_quote("NIFTY MIDCAP 100")
    def smallcap(self): return self.index_quote("NIFTY SMALLCAP 100")


nse_provider = NSEProvider()

__all__ = ["NSEProvider", "nse_provider"]
