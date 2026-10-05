"""Centralized Zerodha Kite provider for TrendForge."""

from __future__ import annotations

import logging
import threading
import time
from functools import wraps
from typing import Any

import pandas as pd

from .market_data_provider import MarketDataProvider

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

import config.settings as settings

logger = logging.getLogger(__name__)


class KiteProvider(MarketDataProvider):
    """Thread-safe singleton wrapper around KiteConnect."""

    _instance: "KiteProvider | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "KiteProvider":
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
        self.live_trading_enabled = settings.LIVE_TRADING_ENABLED
        self.kite = KiteConnect(api_key=self.api_key)
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        self._initialized = True

    def health(self) -> dict[str, Any]:
        """Report configuration state without making a broker/network request."""
        if not self.api_key:
            return {"status": "degraded", "provider": self.__class__.__name__, "reason": "api_key_missing"}
        return {
            "status": "configured",
            "provider": self.__class__.__name__,
            "authenticated": bool(self.access_token),
        }

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        raise NotImplementedError("Kite candles require an instrument token; use the routed market-data adapter.")

    def set_access_token(self, access_token: str) -> None:
        self.access_token = access_token
        self.kite.set_access_token(access_token)

    def login_url(self) -> str:
        return self.kite.login_url()

    def generate_session(self, request_token: str) -> dict[str, Any]:
        data = self.kite.generate_session(request_token, api_secret=self.api_secret)
        self.set_access_token(data["access_token"])
        return data

    def is_logged_in(self) -> bool:
        if not self.access_token:
            return False
        try:
            self.kite.profile()
            return True
        except Exception:
            return False

    def profile(self) -> Any:
        return self.kite.profile()

    def margins(self) -> Any:
        return self.kite.margins()

    def holdings(self) -> Any:
        return self.kite.holdings()

    def positions(self) -> Any:
        return self.kite.positions()

    def orders(self) -> Any:
        return self.kite.orders()

    def trades(self) -> Any:
        return self.kite.trades()

    def instruments(self, exchange: str | None = None) -> Any:
        return self.kite.instruments(exchange) if exchange else self.kite.instruments()

    def ltp(self, instruments: Any) -> Any:
        return self.kite.ltp(instruments)

    def quote(self, instruments: Any) -> Any:
        return self.kite.quote(instruments)

    def historical_data(self, instrument_token: int, from_date: Any, to_date: Any, interval: str, continuous: bool = False, oi: bool = False) -> Any:
        return self.kite.historical_data(instrument_token, from_date, to_date, interval, continuous=continuous, oi=oi)

    def _require_live_trading(self) -> None:
        # Both the runtime opt-in and the instance flag must permit broker writes.
        # Re-check the environment so removing the opt-in disables existing instances.
        import os
        enabled = os.getenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled or not getattr(self, "live_trading_enabled", False):
            raise RuntimeError("Live trading disabled: broker order operations require explicit opt-in")

    def place_order(self, **kwargs: Any) -> Any:
        self._require_live_trading()
        return self.kite.place_order(**kwargs)

    def modify_order(self, variety: str, order_id: str, **kwargs: Any) -> Any:
        self._require_live_trading()
        return self.kite.modify_order(variety=variety, order_id=order_id, **kwargs)

    def cancel_order(self, variety: str, order_id: str) -> Any:
        self._require_live_trading()
        return self.kite.cancel_order(variety=variety, order_id=order_id)

    def order_history(self, order_id: str) -> Any:
        return self.kite.order_history(order_id)

    def order_trades(self, order_id: str) -> Any:
        return self.kite.order_trades(order_id)

    def get_gtts(self) -> Any:
        return self.kite.get_gtts()

    def invalidate_session(self) -> None:
        try:
            if self.access_token:
                self.kite.invalidate_access_token()
        finally:
            self.access_token = None

    @staticmethod
    def retry(func):
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
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
    def safe_quote(self, instruments: Any) -> Any:
        return self.quote(instruments)

    @retry
    def safe_ltp(self, instruments: Any) -> Any:
        return self.ltp(instruments)

    @retry
    def safe_historical(self, *args: Any, **kwargs: Any) -> Any:
        return self.historical_data(*args, **kwargs)


kite_provider = KiteProvider()

__all__ = ["KiteProvider", "kite_provider"]
