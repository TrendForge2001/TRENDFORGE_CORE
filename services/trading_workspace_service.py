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


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


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
        # Keys come only from normalize_index_name: at most three snapshots.
        self._quote_snapshots: dict[str, _QuoteSnapshot] = {}

    def provider_factory(self):
        if self.providers is None and callable(self.provider_factory_getter):
            self.providers = self.provider_factory_getter()
        if self.providers is None:
            raise RuntimeError("Canonical provider factory is unavailable")
        return self.providers

    def quote_provider(self):
        if self._quote_provider is None:
            self._quote_provider = self.provider_factory().quote()
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

        def nullable_number(value: Any) -> float | None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if math.isfinite(number) else None

        for member in members:
            symbol = member["symbol"]
            quote = quote_map.get(f"NSE:{symbol}") or {}
            ohlc = quote.get("ohlc") or {}
            ltp = nullable_number(quote.get("last_price"))
            previous_close = nullable_number(ohlc.get("close"))
            if ltp is not None and ltp > 0:
                quoted += 1
            else:
                ltp = None
            change = (
                ltp - previous_close
                if ltp is not None and previous_close is not None and previous_close > 0
                else None
            )
            change_pct = (
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
        quote = quotes.get(f"NSE:{resolved}") or {}
        ohlc = quote.get("ohlc") or {}
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
