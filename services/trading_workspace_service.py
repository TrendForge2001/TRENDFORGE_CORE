"""Market/watchlist workspace service behind the API provider boundary."""
from __future__ import annotations

from typing import Any, Callable

from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)


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

    def watchlist(self, index_name: str) -> dict[str, Any]:
        normalized = normalize_index_name(index_name)
        payload = self.universe_provider.load(normalized)
        members = payload.get("members") or []
        instruments = [
            f"NSE:{str(item.get('symbol') or '').strip().upper()}"
            for item in members
            if str(item.get("symbol") or "").strip()
        ]
        quote_provider = self.quote_provider()
        safe_quote = getattr(quote_provider, "safe_quote", None)
        quote_map = (
            safe_quote(instruments)
            if instruments and callable(safe_quote)
            else quote_provider.quote(instruments)
            if instruments
            else {}
        )
        rows: list[dict[str, Any]] = []
        for item in members:
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            quote = quote_map.get(f"NSE:{symbol}") or {}
            ohlc = quote.get("ohlc") or {}
            ltp = _number(quote.get("last_price"))
            previous_close = _number(ohlc.get("close"))
            change = ltp - previous_close if previous_close else 0.0
            change_pct = (
                change * 100.0 / previous_close
                if previous_close
                else 0.0
            )
            rows.append(
                {
                    "stock_name": item.get("name") or symbol,
                    "symbol": symbol,
                    "day_change_rs": round(change, 2),
                    "day_change_pct": round(change_pct, 2),
                    "ltp": round(ltp, 2),
                    "sector": item.get("sector"),
                }
            )
        return {
            "status": "ready",
            "index": normalized,
            "count": len(rows),
            "source": payload.get("source"),
            "fetched_at": payload.get("fetched_at"),
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
