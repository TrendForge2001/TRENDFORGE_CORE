"""Compact trading-workspace routes for the R72.3 unified webapp."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.admin_auth import require_admin_api_key
from providers.kite_provider import KiteProvider
from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)


class IndexTechnicalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern="^(intraday|swing)$")
    execute_paper: bool = False

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        return str(value).strip().lower()


def _number(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def attach_trading_workspace_routes(
    app: FastAPI,
    *,
    intelligence_getter: Callable[[], Any],
    paper_getter: Callable[[], Any],
) -> None:
    universe_provider = NSEBroadMarketConstituentProvider()
    kite = KiteProvider()

    def auto_scanner():
        return getattr(app.state, "technical_auto_scanner", None)

    @app.get("/workspace/watchlist/{index_name}")
    def workspace_watchlist(index_name: str) -> dict[str, Any]:
        try:
            normalized = normalize_index_name(unquote(index_name))
            payload = universe_provider.load(normalized)
            members = payload.get("members") or []
            instruments = [
                f"NSE:{str(item.get('symbol') or '').strip().upper()}"
                for item in members
                if str(item.get("symbol") or "").strip()
            ]
            quote_map = kite.safe_quote(instruments) if instruments else {}
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
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/workspace/stock/{symbol}")
    def workspace_stock_detail(
        symbol: str,
        period: str = "6mo",
    ) -> dict[str, Any]:
        resolved = str(symbol or "").strip().upper()
        if not resolved:
            raise HTTPException(status_code=422, detail="symbol is required")
        try:
            quotes = kite.safe_quote([f"NSE:{resolved}"])
            quote = quotes.get(f"NSE:{resolved}") or {}
            ohlc = quote.get("ohlc") or {}
            frame = kite.candles(
                resolved,
                period=period,
                interval="1d",
            )
            candles = [
                {
                    "date": index.isoformat()
                    if hasattr(index, "isoformat")
                    else str(index),
                    "open": _number(row.get("Open")),
                    "high": _number(row.get("High")),
                    "low": _number(row.get("Low")),
                    "close": _number(row.get("Close")),
                    "volume": _number(row.get("Volume")),
                }
                for index, row in frame.tail(180).iterrows()
            ]
            intelligence = intelligence_getter()
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
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/workspace/paper-portfolio")
    def workspace_paper_portfolio() -> dict[str, Any]:
        service = paper_getter()
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Paper trading service is unavailable",
            )
        snapshot = service.snapshot()
        trades = getattr(getattr(service, "runtime", None), "trades", None)
        closed: list[dict[str, Any]] = []
        if trades is not None and callable(getattr(trades, "closed_trades", None)):
            for row in trades.closed_trades() or []:
                closed.append(dict(row) if not isinstance(row, dict) else row)
        return {
            "status": "ready",
            "portfolio": snapshot,
            "closed_trades": closed[:200],
            "safety": {
                "paper_only": True,
                "broker_orders_allowed": False,
            },
        }

    @app.get("/workspace/technical/auto-status")
    def workspace_auto_status() -> dict[str, Any]:
        runner = auto_scanner()
        if runner is None:
            return {"status": "not_supported"}
        return runner.status()

    @app.post(
        "/workspace/technical/run",
        dependencies=[Depends(require_admin_api_key)],
    )
    def workspace_run_technical(
        request: IndexTechnicalRunRequest,
    ) -> dict[str, Any]:
        runner = auto_scanner()
        if runner is None:
            raise HTTPException(
                status_code=503,
                detail="Technical auto scanner is unavailable",
            )
        return runner.trigger(
            request.mode,
            execute_paper=request.execute_paper,
        )


__all__ = [
    "IndexTechnicalRunRequest",
    "attach_trading_workspace_routes",
]
