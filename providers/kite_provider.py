"""Centralized Zerodha Kite provider for TrendForge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import logging
import threading
import time
from typing import Any

import pandas as pd

from .market_data_provider import MarketDataProvider, ProviderAuthenticationError

from providers.kite_errors import KiteException, TokenException
from providers.kite_rest_client import KiteRESTClient as KiteConnect

import config.settings as settings
from core.broker_execution_policy import GuardedKiteClient, require_live_trading

logger = logging.getLogger(__name__)


class KiteProvider(MarketDataProvider):
    """Thread-safe singleton wrapper around the guarded Kite REST client."""

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
        self.kite = KiteConnect(
            api_key=self.api_key, execution_guard=self._require_live_trading
        )
        self._instrument_token_cache: dict[str, int] = {}
        self._instrument_rows: list[dict[str, Any]] = []
        self._instrument_cache_loaded = False
        self.symbol_aliases: dict[str, str] = {}
        self._history_lock = threading.Lock()
        self._last_history_call_at = 0.0
        self._auth_lock = threading.Lock()
        self._auth_checked_at = 0.0
        self._auth_ok = False
        self._auth_error: str | None = None
        if self.access_token:
            self.kite.set_access_token(self.access_token)
        self._initialized = True

    @property
    def kite(self) -> GuardedKiteClient:
        return self._kite_client

    @kite.setter
    def kite(self, client: Any) -> None:
        self._kite_client = GuardedKiteClient(client, self._require_live_trading)

    def _probe_auth(self, *, force: bool = False) -> tuple[bool, str | None]:
        if not self.api_key:
            return False, "api_key_missing"
        if not self.access_token:
            return False, "access_token_missing"

        with self._auth_lock:
            now = time.monotonic()
            if (
                not force
                and self._auth_checked_at > 0
                and now - self._auth_checked_at < 60.0
            ):
                return self._auth_ok, self._auth_error

            try:
                self.kite.profile()
                self._auth_ok = True
                self._auth_error = None
            except TokenException as exc:
                self._auth_ok = False
                self._auth_error = str(exc)
            except Exception as exc:
                self._auth_ok = False
                self._auth_error = f"{type(exc).__name__}: {exc}"

            self._auth_checked_at = now
            return self._auth_ok, self._auth_error

    def validate_live_session(self) -> None:
        ok, error = self._probe_auth()
        if not ok:
            raise ProviderAuthenticationError(
                "Kite authentication failed"
                + (f": {error}" if error else "")
            )

    def health(self) -> dict[str, Any]:
        """Report live Kite authentication state without exposing credentials."""
        ok, error = self._probe_auth()
        payload = {
            "status": "healthy" if ok else "degraded",
            "provider": self.__class__.__name__,
            "authenticated": ok,
            "auth_status": "runtime_verified" if ok else "failed",
        }
        if error:
            payload["auth_error"] = error
        return payload

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
        normalized_rows: list[dict[str, Any]] = []

        for row in rows or []:
            if not isinstance(row, dict):
                continue
            symbol = str(row.get("tradingsymbol") or "").strip().upper()
            token = row.get("instrument_token")
            exchange = str(row.get("exchange") or "NSE").strip().upper()
            if not symbol or token is None:
                continue
            try:
                token_value = int(token)
            except (TypeError, ValueError):
                continue

            mapping[symbol] = token_value
            normalized_rows.append(
                {
                    "tradingsymbol": symbol,
                    "instrument_token": token_value,
                    "exchange": exchange,
                    "name": str(row.get("name") or "").strip().upper(),
                    "instrument_type": str(
                        row.get("instrument_type") or ""
                    ).strip().upper(),
                }
            )

        if not mapping:
            raise RuntimeError("Kite NSE instrument master returned no usable symbols")

        self._instrument_token_cache = mapping
        self._instrument_rows = normalized_rows
        self._instrument_cache_loaded = True

    @staticmethod
    def _compact_symbol(value: str) -> str:
        return "".join(
            ch for ch in str(value or "").upper()
            if ch.isalnum()
        )

    def _discover_instrument_token(
        self,
        key: str,
        resolved: str,
    ) -> tuple[int, str] | None:
        candidates: list[dict[str, Any]] = []
        targets = {
            self._compact_symbol(key),
            self._compact_symbol(resolved),
        }
        targets.discard("")

        for row in getattr(self, "_instrument_rows", []) or []:
            if str(row.get("exchange") or "").upper() != "NSE":
                continue
            trading_symbol = str(
                row.get("tradingsymbol") or ""
            ).strip().upper()
            compact = self._compact_symbol(trading_symbol)
            if compact in targets:
                candidates.append(row)

        if not candidates:
            for row in getattr(self, "_instrument_rows", []) or []:
                if str(row.get("exchange") or "").upper() != "NSE":
                    continue
                trading_symbol = str(
                    row.get("tradingsymbol") or ""
                ).strip().upper()
                compact = self._compact_symbol(trading_symbol)
                if any(
                    compact.startswith(target)
                    for target in targets
                    if len(target) >= 6
                ):
                    candidates.append(row)

        unique = {
            (
                int(row["instrument_token"]),
                str(row["tradingsymbol"]),
            )
            for row in candidates
            if row.get("instrument_token") is not None
        }

        if len(unique) == 1:
            token, trading_symbol = next(iter(unique))
            return token, trading_symbol

        return None

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
        aliases = getattr(self, "symbol_aliases", {})
        resolved = aliases.get(key, key)
        self._load_instrument_tokens()

        for candidate in (resolved, key):
            token = self._instrument_token_cache.get(candidate)
            if token is not None:
                return token

        discovered = self._discover_instrument_token(key, resolved)
        if discovered is not None:
            token, trading_symbol = discovered
            self._instrument_token_cache[key] = token
            self._instrument_token_cache[resolved] = token
            logger.info(
                "Resolved Kite symbol %s via instrument master as %s",
                key,
                trading_symbol,
            )
            return token

        raise KeyError(
            f"Kite instrument token not found for NSE:{key}"
            + (f" (resolved as {resolved})" if resolved != key else "")
        )

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
        if hasattr(self, "kite") and getattr(self, "access_token", None):
            self.validate_live_session()

        ordered: list[str] = []
        seen: set[str] = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)

        results: dict[str, pd.DataFrame] = {}
        failures: dict[str, str] = {}
        workers = min(8, len(ordered))
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
        self._auth_checked_at = 0.0
        self._auth_ok = False
        self._auth_error = None
        self._instrument_token_cache = {}
        self._instrument_rows = []
        self._instrument_cache_loaded = False

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
        require_live_trading(getattr(self, "live_trading_enabled", False))

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

    def _retry_read(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if method not in {"quote", "ltp", "historical_data"}:
            raise ValueError("Only supported Kite market-data reads can be retried")
        read = getattr(self.kite, method)
        delay = 1
        for attempt in range(3):
            try:
                return read(*args, **kwargs)
            except KiteException:
                if attempt == 2:
                    raise
                time.sleep(delay)
                delay *= 2

    def safe_quote(self, instruments: Any) -> Any:
        return self._retry_read("quote", instruments)

    def safe_ltp(self, instruments: Any) -> Any:
        return self._retry_read("ltp", instruments)

    def safe_historical(self, *args: Any, **kwargs: Any) -> Any:
        return self._retry_read("historical_data", *args, **kwargs)


kite_provider = KiteProvider()

__all__ = ["KiteProvider", "kite_provider"]
