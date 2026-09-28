"""Centralized Zerodha Kite provider for TrendForge."""
from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

import config.settings as settings
from .market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class KiteProvider(MarketDataProvider):
    """Thread-safe singleton wrapper around KiteConnect."""

    _instance: "KiteProvider | None" = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self.api_key = settings.KITE_API_KEY or ""
        self.api_secret = settings.KITE_API_SECRET or ""
        self.access_token = settings.KITE_ACCESS_TOKEN
        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        self._initialized = True

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d"):
        raise NotImplementedError("Kite historical candles require instrument-token/date-range routing")

    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token
        self.kite.set_access_token(access_token)

    def login_url(self): return self.kite.login_url()
    def generate_session(self, request_token): 
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.set_access_token(data["access_token"])
        return data
    def is_logged_in(self):
        if not self.access_token:
            return False
        try:
            self.kite.profile()
            return True
        except Exception:
            return False
    def profile(self): return self.kite.profile()
    def margins(self): return self.kite.margins()
    def holdings(self): return self.kite.holdings()
    def positions(self): return self.kite.positions()
    def orders(self): return self.kite.orders()
    def trades(self): return self.kite.trades()
    def instruments(self, exchange=None): return self.kite.instruments(exchange) if exchange else self.kite.instruments()
    def ltp(self, instruments): return self.kite.ltp(instruments)
    def quote(self, instruments): return self.kite.quote(instruments)
    def historical_data(self, instrument_token, from_date, to_date, interval, continuous=False, oi=False):
        return self.kite.historical_data(instrument_token, from_date, to_date, interval, continuous=continuous, oi=oi)
    def place_order(self, **kwargs): return self.kite.place_order(**kwargs)
    def modify_order(self, variety, order_id, **kwargs): return self.kite.modify_order(variety=variety, order_id=order_id, **kwargs)
    def cancel_order(self, variety, order_id): return self.kite.cancel_order(variety=variety, order_id=order_id)
    def order_history(self, order_id): return self.kite.order_history(order_id)
    def order_trades(self, order_id): return self.kite.order_trades(order_id)
    def get_gtts(self): return self.kite.get_gtts()
    def invalidate_session(self):
        try:
            if self.access_token:
                self.kite.invalidate_access_token()
        finally:
            self.access_token = None

    @staticmethod
    def retry(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = 1
            for attempt in range(3):
                try:
                    return func(*args, **kwargs)
                except KiteException:
                    if attempt == 2:
                        raise
                    time.sleep(delay)
                    delay *= 2
        return wrapper

    @retry
    def safe_quote(self, instruments): return self.quote(instruments)

    @retry
    def safe_ltp(self, instruments): return self.ltp(instruments)

    @retry
    def safe_historical(self, *args, **kwargs): return self.historical_data(*args, **kwargs)


kite_provider = KiteProvider()
__all__ = ["KiteProvider", "kite_provider"]
