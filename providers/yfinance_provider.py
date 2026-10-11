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
        self.symbol_aliases: dict[str, str] = {}
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
        symbol = symbol.strip().upper()
        if symbol.startswith("^") or symbol.endswith((".NS", ".BO")):
            return symbol
        return f"{symbol}.NS"

    def set_symbol_aliases(self, aliases: dict[str, str] | None) -> None:
        self.symbol_aliases = {
            str(symbol or "").strip().upper(): str(alias or "").strip().upper()
            for symbol, alias in dict(aliases or {}).items()
            if str(symbol or "").strip() and str(alias or "").strip()
        }

    def _resolved_symbol(self, symbol: str) -> str:
        raw = str(symbol or "").strip().upper()
        alias = self.symbol_aliases.get(raw, raw)
        return self.normalize_symbol(alias)

    def ticker(self, symbol: str):
        return yf.Ticker(self._resolved_symbol(symbol))

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
        normalized = [self._resolved_symbol(s) for s in symbols]
        return yf.download(
            normalized,
            period=period,
            interval=interval,
            group_by="ticker",
            threads=4,
            progress=False,
            auto_adjust=False,
        )

    def batch_candles_with_errors(
        self,
        symbols: list[str],
        period: str = "6mo",
        interval: str = "1d",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        """Fetch a scanner batch with one Yahoo download request.

        Returned frames stay provider-native; MarketDataAdapter owns canonical
        OHLCV normalization. Missing symbols remain explicit failures.
        """
        ordered: list[str] = []
        seen: set[str] = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)

        if not ordered:
            return {}, {}

        try:
            payload = self.download(
                ordered,
                period=period,
                interval=interval,
            )
        except Exception as exc:
            message = str(exc)
            return {}, {symbol: message for symbol in ordered}

        results: dict[str, pd.DataFrame] = {}
        failures: dict[str, str] = {}
        multi = isinstance(payload, pd.DataFrame) and isinstance(
            payload.columns, pd.MultiIndex
        )

        for symbol in ordered:
            normalized = self._resolved_symbol(symbol)
            try:
                if not isinstance(payload, pd.DataFrame) or payload.empty:
                    raise ValueError("Yahoo batch returned no candle data")

                if multi:
                    level0 = {
                        str(value)
                        for value in payload.columns.get_level_values(0)
                    }
                    level1 = {
                        str(value)
                        for value in payload.columns.get_level_values(1)
                    }
                    if normalized in level0:
                        frame = payload[normalized].copy()
                    elif normalized in level1:
                        frame = payload.xs(
                            normalized,
                            axis=1,
                            level=1,
                        ).copy()
                    else:
                        raise ValueError(
                            "Yahoo batch omitted symbol"
                        )
                elif len(ordered) == 1:
                    frame = payload.copy()
                else:
                    raise ValueError(
                        "Yahoo batch response is not grouped by ticker"
                    )

                frame = frame.dropna(how="all")
                if frame.empty:
                    raise ValueError(
                        "Yahoo batch returned no candle rows"
                    )
                results[symbol] = frame
            except Exception as exc:
                failures[symbol] = str(exc)

        # Recover a small number of symbols omitted from an otherwise
        # successful multi-ticker response. This stays deliberately capped so
        # the scale path cannot regress into one Yahoo request per symbol.
        missing = [
            symbol
            for symbol in ordered
            if symbol not in results
        ]
        if 0 < len(missing) <= 4:
            for symbol in missing:
                attempts: list[str] = []
                recovered: pd.DataFrame | None = None

                # First retry with Yahoo's download path rather than
                # Ticker.history(). Newly listed NSE securities can appear in
                # one endpoint before the other.
                recovery_periods = [period]
                if str(period).lower() == "6mo":
                    recovery_periods.append("3mo")

                for recovery_period in recovery_periods:
                    try:
                        payload = self.download(
                            [symbol],
                            period=recovery_period,
                            interval=interval,
                        )
                        if not isinstance(payload, pd.DataFrame) or payload.empty:
                            raise ValueError(
                                "Yahoo single-symbol download returned no rows"
                            )

                        normalized = self._resolved_symbol(symbol)
                        if isinstance(payload.columns, pd.MultiIndex):
                            level0 = {
                                str(value)
                                for value in payload.columns.get_level_values(0)
                            }
                            level1 = {
                                str(value)
                                for value in payload.columns.get_level_values(1)
                            }
                            if normalized in level0:
                                frame = payload[normalized].copy()
                            elif normalized in level1:
                                frame = payload.xs(
                                    normalized,
                                    axis=1,
                                    level=1,
                                ).copy()
                            else:
                                frame = payload.copy()
                        else:
                            frame = payload.copy()

                        frame = frame.dropna(how="all")
                        if frame.empty:
                            raise ValueError(
                                "Yahoo single-symbol download returned no candle rows"
                            )

                        recovered = frame
                        break
                    except Exception as exc:
                        attempts.append(
                            f"download[{recovery_period}]:{exc}"
                        )

                if recovered is None:
                    try:
                        frame = self.historical_data(
                            symbol,
                            period=period,
                            interval=interval,
                            auto_adjust=False,
                        )
                        if frame is None or frame.empty:
                            raise ValueError(
                                "Yahoo targeted history returned no candle rows"
                            )
                        recovered = frame
                    except Exception as exc:
                        attempts.append(f"history[{period}]:{exc}")

                if recovered is not None:
                    results[symbol] = recovered
                    failures.pop(symbol, None)
                else:
                    failures[symbol] = (
                        f"{failures.get(symbol, 'Yahoo batch omitted symbol')}; "
                        "targeted recovery failed: "
                        + " | ".join(attempts)
                    )

        return results, failures

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
