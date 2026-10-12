"""Centralized Zerodha Kite provider for TrendForge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
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
        self._instrument_token_cache: dict[str, int] = {}
        self._instrument_cache_loaded = False
        self.symbol_aliases: dict[str, str] = {}
        self._history_lock = threading.Lock()
        self._last_history_call_at = 0.0
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

    @staticmethod
    def _history_window(period: str) -> tuple[datetime, datetime]:
        now = datetime.now(timezone.utc)
        value = str(period or "6mo").strip().lower()
        days = {
            "1mo": 31,
            "3mo": 93,
            "6mo": 186,
            "1y": 366,
            "2y": 732,
            "5y": 1830,
        }.get(value)
        if days is None:
            if value.endswith("d") and value[:-1].isdigit():
                days = max(1, int(value[:-1]))
            else:
                raise ValueError(f"Unsupported Kite history period: {period}")
        return now - timedelta(days=days), now

    @staticmethod
    def _kite_interval(interval: str) -> str:
        value = str(interval or "1d").strip().lower()
        mapping = {
            "1d": "day",
            "day": "day",
            "1m": "minute",
            "minute": "minute",
            "3m": "3minute",
            "3minute": "3minute",
            "5m": "5minute",
            "5minute": "5minute",
            "10m": "10minute",
            "10minute": "10minute",
            "15m": "15minute",
            "15minute": "15minute",
            "30m": "30minute",
            "30minute": "30minute",
            "60m": "60minute",
            "1h": "60minute",
            "60minute": "60minute",
        }
        if value not in mapping:
            raise ValueError(f"Unsupported Kite candle interval: {interval}")
        return mapping[value]

    def _load_instrument_tokens(self) -> None:
        if self._instrument_cache_loaded:
            return
        if not self.access_token:
            raise RuntimeError("Kite access token is not configured")
        rows = self.instruments("NSE")
        mapping: dict[str, int] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("tradingsymbol") or "").strip().upper()
            token = row.get("instrument_token")
            if not symbol or token is None:
                continue
            try:
                mapping[symbol] = int(token)
            except (TypeError, ValueError):
                continue
        if not mapping:
            raise RuntimeError("Kite NSE instrument master returned no usable symbols")
        self._instrument_token_cache = mapping
        self._instrument_cache_loaded = True

    def set_symbol_aliases(self, aliases: dict[str, str] | None) -> None:
        self.symbol_aliases = {
            str(symbol or "").strip().upper(): str(alias or "").strip().upper()
            for symbol, alias in dict(aliases or {}).items()
            if str(symbol or "").strip() and str(alias or "").strip()
        }

    def instrument_token_for_symbol(self, symbol: str) -> int:
        key = str(symbol or "").strip().upper()
        if not key:
            raise ValueError("Symbol is required")
        resolved = self.symbol_aliases.get(key, key)
        self._load_instrument_tokens()
        token = self._instrument_token_cache.get(resolved)
        if token is None:
            raise KeyError(
                f"Kite instrument token not found for NSE:{key}"
                + (f" (resolved as {resolved})" if resolved != key else "")
            )
        return token

    def _pace_history(self) -> None:
        # Kite historical-data limits are broker-enforced. Keep a conservative
        # minimum spacing so staged scans do not burst the endpoint.
        with self._history_lock:
            elapsed = time.monotonic() - self._last_history_call_at
            delay = 0.36 - elapsed
            if delay > 0:
                time.sleep(delay)
            self._last_history_call_at = time.monotonic()

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        if not self.access_token:
            raise RuntimeError("Kite historical candles require an authenticated access token")

        token = self.instrument_token_for_symbol(symbol)
        from_date, to_date = self._history_window(period)
        kite_interval = self._kite_interval(interval)
        self._pace_history()
        rows = self.safe_historical(
            token,
            from_date,
            to_date,
            kite_interval,
            continuous=False,
            oi=False,
        )
        frame = pd.DataFrame(rows or [])
        if frame.empty:
            raise ValueError(f"Kite returned no historical candles for {symbol}")

        rename = {
            "date": "date",
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
        frame = frame.rename(columns=rename)
        required = ["Open", "High", "Low", "Close", "Volume"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ValueError(
                f"Kite returned incomplete OHLCV data for {symbol}: {missing}"
            )
        if "date" in frame.columns:
            frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
            frame = frame.set_index("date")
        return frame.loc[:, required]

    def batch_candles_with_errors(
        self,
        symbols: list[str],
        period: str = "6mo",
        interval: str = "1d",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)

        results: dict[str, pd.DataFrame] = {}
        failures: dict[str, str] = {}
        workers = min(3, len(ordered))
        if workers <= 0:
            return results, failures

        with ThreadPoolExecutor(
            max_workers=workers,
            thread_name_prefix="trendforge-kite-history",
        ) as executor:
            futures = {
                executor.submit(
                    self.candles,
                    symbol,
                    period=period,
                    interval=interval,
                ): symbol
                for symbol in ordered
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    failures[symbol] = str(exc)

        return results, failures

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
