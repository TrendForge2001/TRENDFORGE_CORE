"""Centralized NSE market-data provider with caching and resilient sessions."""

from __future__ import annotations

from datetime import date, timedelta
import logging
import threading
import time
from functools import wraps
from typing import Any
from urllib.parse import urlparse

import pandas as pd
import requests

from .market_data_provider import MarketDataProvider

logger = logging.getLogger(__name__)


class NSEProvider(MarketDataProvider):
    _instance = None
    _lock = threading.Lock()

    BASE_URL = "https://www.nseindia.com"
    CACHE_TTL = 60
    RATE_LIMIT_COOLDOWN = 120
    ALLOWED_DOCUMENT_HOSTS = {
        "nsearchives.nseindia.com",
        "archives.nseindia.com",
        "www.nseindia.com",
    }

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "application/json,text/plain,*/*",
        "Referer": "https://www.nseindia.com/",
        "Connection": "keep-alive",
    }

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
        self.cache: dict[Any, tuple[Any, float]] = {}
        self._session_ready = False
        self._rate_limited_until = 0.0
        self._last_error: str | None = None
        self._last_success_at: float | None = None
        self._initialized = True

    def _initialize_session(self):
        try:
            response = self.session.get(self.BASE_URL, timeout=10)
            response.raise_for_status()
            self._session_ready = True
        except requests.RequestException as exc:
            self._session_ready = False
            self._last_error = f"session_warmup:{exc}"
            logger.warning("NSE session initialization failed: %s", exc)

    def _ensure_session(self):
        if not self._session_ready:
            self._initialize_session()
        if not self._session_ready:
            raise RuntimeError(
                self._last_error or "NSE session could not be initialized"
            )

    def _cooldown_remaining(self) -> int:
        return max(0, int(round(self._rate_limited_until - time.time())))

    def _ensure_not_rate_limited(self) -> None:
        remaining = self._cooldown_remaining()
        if remaining > 0:
            raise RuntimeError(
                f"NSE upstream cooldown active; retry in {remaining}s"
            )

    def health(self) -> dict[str, Any]:
        """Report provider state without generating a new network request."""
        remaining = self._cooldown_remaining()
        runtime_status = "configured"
        status = "configured"

        if remaining > 0:
            runtime_status = "rate_limited"
            status = "degraded"
        elif self._last_success_at is not None:
            runtime_status = "runtime_verified"

        return {
            "status": status,
            "provider": self.__class__.__name__,
            "session_ready": self._session_ready,
            "network_probe": False,
            "runtime_status": runtime_status,
            "last_error": self._last_error,
            "last_success_at_epoch": self._last_success_at,
            "retry_after_seconds": remaining,
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

    def _decode_json_response(self, response: requests.Response) -> Any:
        if response.status_code == 429:
            self._rate_limited_until = (
                time.time() + self.RATE_LIMIT_COOLDOWN
            )
            raise RuntimeError(
                "NSE upstream rate limited the request (HTTP 429)"
            )

        if response.status_code in {401, 403}:
            self._session_ready = False

        response.raise_for_status()

        text = (response.text or "").strip()
        content_type = str(response.headers.get("Content-Type") or "").lower()

        if not text:
            self._session_ready = False
            raise RuntimeError(
                f"NSE returned an empty response (HTTP {response.status_code})"
            )

        looks_json = text.startswith("{") or text.startswith("[")
        if "json" not in content_type and not looks_json:
            self._session_ready = False
            preview = " ".join(text[:120].split())
            raise RuntimeError(
                "NSE returned a non-JSON response "
                f"(HTTP {response.status_code}, content-type={content_type or 'unknown'}, "
                f"preview={preview!r})"
            )

        try:
            return response.json()
        except ValueError as exc:
            self._session_ready = False
            raise RuntimeError(
                "NSE returned malformed JSON "
                f"(HTTP {response.status_code}, content-type={content_type or 'unknown'})"
            ) from exc

    @retry
    def _get(self, endpoint, params=None):
        key = (endpoint, tuple(sorted((params or {}).items())))
        cached = self._cache_get(key)
        if cached is not None:
            return cached

        self._ensure_not_rate_limited()
        self._ensure_session()

        try:
            response = self.session.get(
                f"{self.BASE_URL}{endpoint}",
                params=params,
                timeout=15,
            )
            data = self._decode_json_response(response)
        except Exception as exc:
            self._last_error = str(exc)
            raise

        self._cache_set(key, data)
        self._last_success_at = time.time()
        self._last_error = None
        return data

    @staticmethod
    def _date_window(days: int) -> tuple[str, str]:
        safe_days = max(1, min(int(days), 3650))
        end = date.today()
        start = end - timedelta(days=safe_days)
        return start.strftime("%d-%m-%Y"), end.strftime("%d-%m-%Y")

    def candles(
        self,
        symbol: str,
        period: str = "6mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        raise NotImplementedError(
            "NSE provider does not expose historical candles through this adapter."
        )

    def market_status(self):
        return self._get("/api/marketStatus")

    def index_quote(self, index_name):
        return self._get("/api/allIndices", {"index": index_name})

    def equity_quote(self, symbol):
        return self._get("/api/quote-equity", {"symbol": str(symbol).upper()})

    def quote(self, symbol):
        return self.equity_quote(symbol)

    def option_chain(self, symbol):
        return self._get(
            "/api/option-chain-equities",
            {"symbol": str(symbol).upper()},
        )

    def market_breadth(self):
        return self._get(
            "/api/equity-stockIndices",
            {"index": "NIFTY 50"},
        )

    def top_gainers(self):
        return self._get(
            "/api/live-analysis-variations",
            {"index": "gainers"},
        )

    def top_losers(self):
        return self._get(
            "/api/live-analysis-variations",
            {"index": "losers"},
        )

    def most_active(self):
        return self._get("/api/live-analysis-most-active-securities")

    def fii_dii(self):
        return self._get("/api/fiiDiiTradeReact")

    def holidays(self):
        return self._get("/api/holiday-master", {"type": "trading"})

    def circulars(self):
        return self._get("/api/circulars")

    def corporate_actions(self, symbol: str | None = None, days: int = 120):
        from_date, to_date = self._date_window(days)
        params: dict[str, Any] = {
            "index": "equities",
            "from_date": from_date,
            "to_date": to_date,
        }
        if symbol:
            params["symbol"] = str(symbol).strip().upper()
        return self._get("/api/corporates-corporateActions", params)

    def shareholding_filings(self, symbol: str):
        return self._get(
            "/api/corporate-share-holdings-master",
            {
                "index": "equities",
                "symbol": str(symbol).strip().upper(),
            },
        )

    @retry
    def public_document(self, url: str) -> str:
        parsed = urlparse(str(url or "").strip())
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or host not in self.ALLOWED_DOCUMENT_HOSTS
        ):
            raise ValueError(
                "NSE public document URL is outside the allowed archive hosts"
            )

        key = ("public_document", str(url))
        cached = self._cache_get(key)
        if cached is not None:
            return str(cached)

        headers = dict(self.HEADERS)
        headers["Accept"] = "application/xml,text/xml,text/plain,*/*"

        response = self.session.get(
            str(url),
            headers=headers,
            timeout=30,
        )
        if response.status_code == 429:
            self._rate_limited_until = (
                time.time() + self.RATE_LIMIT_COOLDOWN
            )
            raise RuntimeError(
                "NSE archive rate limited the request (HTTP 429)"
            )
        response.raise_for_status()

        text = str(response.text or "").strip()
        if not text or not text.startswith("<"):
            raise RuntimeError(
                "NSE archive returned a non-XML/empty document"
            )

        self._cache_set(key, text)
        self._last_success_at = time.time()
        self._last_error = None
        return text

    def bulk_deals(self, days: int = 30):
        from_date, to_date = self._date_window(days)
        return self._get(
            "/api/historicalOR/bulk-block-short-deals",
            {
                "optionType": "bulk_deals",
                "from": from_date,
                "to": to_date,
            },
        )

    def block_deals(self, days: int = 30):
        from_date, to_date = self._date_window(days)
        return self._get(
            "/api/historicalOR/bulk-block-short-deals",
            {
                "optionType": "block_deals",
                "from": from_date,
                "to": to_date,
            },
        )

    def bhavcopy(self):
        return self._get("/api/reports", {"archives": "downloads"})

    def advance_decline(self):
        advances = declines = unchanged = 0
        for stock in self.market_breadth().get("data", []):
            change = stock.get("change", 0) or 0
            if change > 0:
                advances += 1
            elif change < 0:
                declines += 1
            else:
                unchanged += 1
        return {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
        }

    def nifty50(self):
        return self.index_quote("NIFTY 50")

    def banknifty(self):
        return self.index_quote("NIFTY BANK")

    def finnifty(self):
        return self.index_quote("NIFTY FINANCIAL SERVICES")

    def midcap(self):
        return self.index_quote("NIFTY MIDCAP 100")

    def smallcap(self):
        return self.index_quote("NIFTY SMALLCAP 100")


nse_provider = NSEProvider()

__all__ = ["NSEProvider", "nse_provider"]
