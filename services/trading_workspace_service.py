"""Market/watchlist workspace service behind the API provider boundary."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable
import math
import threading
import time
from uuid import uuid4

from providers.kite_errors import TokenException
from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)

_LOG = logging.getLogger("trendforge.workspace")


@dataclass(frozen=True)
class _QuoteSnapshot:
    instruments: tuple[str, ...]
    quotes: dict[str, Any]
    error: str | None
    reference: str | None
    fetched_at: str
    created_at: float


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


_CREDENTIAL_FIELDS = frozenset({
    "apikey", "apisecret", "accesstoken", "requesttoken", "refreshtoken",
    "publictoken", "enctoken", "authorization", "cookie", "setcookie",
    "token", "password", "secret", "sessiontoken",
})


def _account_view(value: Any) -> Any:
    """Keep broker account data while excluding structured transport credentials."""
    if isinstance(value, dict):
        return {
            key: _account_view(item)
            for key, item in value.items()
            if "".join(char for char in str(key).lower() if char.isalnum())
            not in _CREDENTIAL_FIELDS
        }
    if isinstance(value, list):
        return [_account_view(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Kite account data contains an invalid number")
    return value


class TradingWorkspaceService:
    def __init__(
        self,
        *,
        intelligence_getter: Callable[[], Any],
        paper_getter: Callable[[], Any],
        universe_provider: NSEBroadMarketConstituentProvider | None = None,
        provider_factory: Any | None = None,
        provider_factory_getter: Callable[[], Any] | None = None,
        quote_cache_ttl: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.intelligence_getter = intelligence_getter
        self.paper_getter = paper_getter
        self.universe_provider = (
            universe_provider or NSEBroadMarketConstituentProvider()
        )
        self.providers = provider_factory
        self.provider_factory_getter = provider_factory_getter
        self._quote_provider = None
        self._market_data = None
        self.quote_cache_ttl = max(0.0, min(60.0, float(quote_cache_ttl)))
        self._clock = clock
        self._quote_lock = threading.Lock()
        # Keys come only from normalize_index_name: at most four snapshots.
        self._quote_snapshots: dict[str, _QuoteSnapshot] = {}

    def provider_factory(self):
        if self.providers is None and callable(self.provider_factory_getter):
            self.providers = self.provider_factory_getter()
        if self.providers is None:
            raise RuntimeError("Canonical provider factory is unavailable")
        return self.providers

    def quote_provider(self):
        if self._quote_provider is None:
            factory = self.provider_factory()
            # Production watchlists must not silently switch from Kite to
            # Yahoo/NSE quotes when the Kite token expires.
            kite_getter = getattr(factory, "_default_kite", None)
            self._quote_provider = (
                kite_getter() if callable(kite_getter) else factory.quote()
            )
        return self._quote_provider

    def market_data(self):
        if self._market_data is None:
            self._market_data = self.provider_factory().kite_market_data()
        return self._market_data

    def _watchlist_quotes(
        self, index_name: str, instruments: list[str],
    ) -> tuple[_QuoteSnapshot, bool]:
        """Coalesce quote reads, including failures, across concurrent polling."""
        name = normalize_index_name(index_name)
        members = tuple(instruments)
        with self._quote_lock:
            cached = self._quote_snapshots.get(name)
            if (
                cached is not None
                and cached.instruments == members
                and self._clock() - cached.created_at < self.quote_cache_ttl
            ):
                return cached, True
            quote_map: dict[str, Any] = {}
            error = None
            reference = None
            if instruments:
                try:
                    quote_provider = self.quote_provider()
                    method = getattr(quote_provider, "safe_quote", None)
                    response = (
                        method(instruments)
                        if callable(method)
                        else quote_provider.quote(instruments)
                    ) or {}
                    if not isinstance(response, dict):
                        raise TypeError("Kite quote response must be a mapping")
                    quote_map = response
                except Exception as exc:
                    error = "Kite quotes temporarily unavailable"
                    reference = uuid4().hex[:12]
                    _LOG.warning(
                        "workspace_quote_unavailable reference=%s exception_type=%s",
                        reference, type(exc).__name__,
                    )
            snapshot = _QuoteSnapshot(
                instruments=members,
                quotes=quote_map,
                error=error,
                reference=reference,
                fetched_at=datetime.now(timezone.utc).isoformat(),
                created_at=self._clock(),
            )
            self._quote_snapshots[name] = snapshot
            return snapshot, False

    def constituents(self, index_name: str) -> dict[str, Any]:
        """Official, validated NSE members; independent of Kite authentication."""
        normalized = normalize_index_name(index_name)
        payload = self.universe_provider.load(normalized)
        members = [
            {
                "stock_name": item.get("name") or item.get("symbol"),
                "symbol": str(item.get("symbol") or "").strip().upper(),
                "sector": item.get("sector"),
            }
            for item in payload.get("members") or []
            if str(item.get("symbol") or "").strip()
        ]
        return {
            "status": "ready",
            "index": normalized,
            "count": len(members),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
            "stale": bool(payload.get("stale")),
            "snapshot_storage": payload.get("snapshot_storage"),
            "snapshot_as_of": payload.get("snapshot_as_of"),
            "source_warning": payload.get("source_warning"),
            "rows": members,
        }

    def watchlist(self, index_name: str) -> dict[str, Any]:
        """Return members even when Kite quote retrieval fails.

        Missing prices and changes remain null, never misleading zeroes.
        """
        payload = self.constituents(index_name)
        members = payload["rows"]
        instruments = [f"NSE:{item['symbol']}" for item in members]
        snapshot, cached = self._watchlist_quotes(payload["index"], instruments)
        quote_map = snapshot.quotes

        rows: list[dict[str, Any]] = []
        quoted = 0

        for member in members:
            symbol = member["symbol"]
            quote = quote_map.get(f"NSE:{symbol}")
            quote = quote if isinstance(quote, dict) else {}
            ohlc = quote.get("ohlc")
            ohlc = ohlc if isinstance(ohlc, dict) else {}
            ltp = _number(quote.get("last_price"))
            previous_close = _number(ohlc.get("close"))
            if ltp is not None and ltp > 0:
                quoted += 1
            else:
                ltp = None
            change = (
                ltp - previous_close
                if ltp is not None and previous_close is not None and previous_close > 0
                else None
            )
            change_pct = _number(
                change * 100.0 / previous_close
                if change is not None and previous_close
                else None
            )
            rows.append(
                {
                    "stock_name": member["stock_name"],
                    "symbol": symbol,
                    "day_change_rs": round(change, 2) if change is not None else None,
                    "day_change_pct": round(change_pct, 2) if change_pct is not None else None,
                    "ltp": round(ltp, 2) if ltp is not None else None,
                    "sector": member.get("sector"),
                }
            )
        return {
            **payload,
            "status": "ready" if quoted == len(rows) else "degraded",
            "count": len(rows),
            "quoted_count": quoted,
            "quote_status": (
                "available" if quoted == len(rows)
                else "partial" if quoted
                else "unavailable"
            ),
            "quote_error": snapshot.error,
            "quote_error_code": "WORKSPACE_QUOTES_UNAVAILABLE" if snapshot.error else None,
            "quote_error_reference": snapshot.reference,
            "quote_cache": {
                "cached": cached,
                "fetched_at": snapshot.fetched_at,
                "age_seconds": round(max(0.0, self._clock() - snapshot.created_at), 3),
                "ttl_seconds": self.quote_cache_ttl,
                "scope": "one Python process",
            },
            "rows": rows,
        }

    def stock_detail(
        self,
        symbol: str,
        *,
        period: str = "6mo",
    ) -> dict[str, Any]:
        resolved = str(symbol or "").strip().upper()
        if not resolved:
            raise ValueError("symbol is required")
        quote_provider = self.quote_provider()
        safe_quote = getattr(quote_provider, "safe_quote", None)
        quotes = (
            safe_quote([f"NSE:{resolved}"])
            if callable(safe_quote)
            else quote_provider.quote([f"NSE:{resolved}"])
        )
        quote = quotes.get(f"NSE:{resolved}") if isinstance(quotes, dict) else None
        quote = quote if isinstance(quote, dict) else {}
        ohlc = quote.get("ohlc")
        ohlc = ohlc if isinstance(ohlc, dict) else {}
        frame = self.market_data().candles(
            resolved,
            period=period,
            interval="1d",
        )
        candles = [
            {
                "date": index.isoformat()
                if hasattr(index, "isoformat")
                else str(index),
                "open": _number(row.get("open")),
                "high": _number(row.get("high")),
                "low": _number(row.get("low")),
                "close": _number(row.get("close")),
                "volume": _number(row.get("volume")),
            }
            for index, row in frame.tail(180).iterrows()
        ]
        intelligence = self.intelligence_getter()
        news = (
            intelligence.news(resolved, limit=30)
            if intelligence is not None
            else {"events": [], "count": 0}
        )
        actions = (
            intelligence.corporate_actions(resolved, limit=30)
            if intelligence is not None
            else {"events": [], "count": 0}
        )
        return {
            "status": "ready",
            "symbol": resolved,
            "ltp": _number(quote.get("last_price")),
            "ohlc": {
                "open": _number(ohlc.get("open")),
                "high": _number(ohlc.get("high")),
                "low": _number(ohlc.get("low")),
                "previous_close": _number(ohlc.get("close")),
            },
            "candles": candles,
            "news": news,
            "corporate_actions": actions,
            "data_provider": "KiteProvider",
        }

    def kite_session(self) -> dict[str, Any]:
        """Read the broker account only after a verified session probe."""
        unavailable = {
            "status": "unavailable",
            "authenticated": False,
            "broker_orders_allowed": False,
            "read_only": True,
            "positions": {},
            "holdings": [],
            "orders": [],
            "margins": {},
        }
        try:
            broker = self.provider_factory()._default_kite()
            health = broker.health()
        except Exception as exc:
            from providers.kite_diagnostics import session_failure
            return {**unavailable, "diagnostic": session_failure(exc)}
        if not isinstance(health, dict) or health.get("authenticated") is not True:
            from providers.kite_diagnostics import safe_session_failure
            return {**unavailable, "diagnostic": safe_session_failure(health if isinstance(health, dict) else {})}
        try:
            positions = broker.positions()
            holdings = broker.holdings()
            orders = broker.orders()
            margins = broker.margins()
        except TokenException as exc:
            # A cached successful health probe cannot outlive token revocation.
            from providers.kite_diagnostics import session_failure
            return {**unavailable, "diagnostic": session_failure(exc)}
        if (
            not isinstance(positions, dict)
            or not all(
                isinstance(positions.get(book), list)
                and all(isinstance(row, dict) for row in positions[book])
                for book in ("net", "day")
            )
            or not isinstance(holdings, list)
            or not all(isinstance(row, dict) for row in holdings)
            or not isinstance(orders, list)
            or not all(isinstance(row, dict) for row in orders)
            or not isinstance(margins, dict)
        ):
            raise ValueError("Kite account data has an invalid shape")
        return {
            "status": "ready",
            "authenticated": True,
            "read_only": True,
            "broker_orders_allowed": False,
            "positions": _account_view(positions),
            "holdings": _account_view(holdings),
            "orders": _account_view(orders[-50:]),
            "margins": _account_view(margins),
        }

    def paper_portfolio(self) -> dict[str, Any]:
        service = self.paper_getter()
        if service is None:
            raise RuntimeError("Paper trading service is unavailable")
        snapshot = service.snapshot()
        trades = getattr(
            getattr(service, "runtime", None),
            "trades",
            None,
        )
        closed: list[dict[str, Any]] = []
        if trades is not None and callable(
            getattr(trades, "closed_trades", None)
        ):
            for row in trades.closed_trades() or []:
                closed.append(
                    dict(row)
                    if not isinstance(row, dict)
                    else row
                )
        return {
            "status": "ready",
            "portfolio": snapshot,
            "closed_trades": closed[:200],
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
            },
        }


__all__ = ["TradingWorkspaceService"]
