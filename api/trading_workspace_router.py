"""Compact trading-workspace routes for the R72.3 unified webapp."""
from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.admin_auth import require_admin_api_key
from services.trading_workspace_service import TradingWorkspaceService


class IndexTechnicalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern="^(intraday|swing)$")
    execute_paper: bool = False

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        return str(value).strip().lower()


def attach_trading_workspace_routes(
    app: FastAPI,
    *,
    intelligence_getter: Callable[[], Any],
    paper_getter: Callable[[], Any],
    provider_factory: Any | None = None,
    provider_factory_getter: Callable[[], Any] | None = None,
) -> None:
    workspace = TradingWorkspaceService(
        intelligence_getter=intelligence_getter,
        paper_getter=paper_getter,
        provider_factory=provider_factory,
        provider_factory_getter=provider_factory_getter,
    )

    def auto_scanner():
        return getattr(app.state, "technical_auto_scanner", None)

    @app.get("/workspace/watchlist/{index_name}/constituents")
    def workspace_constituents(index_name: str) -> dict[str, Any]:
        try:
            return workspace.constituents(unquote(index_name))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Index constituents temporarily unavailable") from exc

    @app.get("/workspace/watchlist/{index_name}")
    def workspace_watchlist(index_name: str) -> dict[str, Any]:
        try:
            return workspace.watchlist(unquote(index_name))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Watchlist temporarily unavailable") from exc

    @app.get("/workspace/stock/{symbol}")
    def workspace_stock_detail(
        symbol: str,
        period: str = Query(default="6mo", pattern=r"^(1d|5d|1mo|3mo|6mo|1y|2y|5y)$"),
    ) -> dict[str, Any]:
        symbol = symbol.strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,39}", symbol) or ".." in symbol:
            raise HTTPException(status_code=422, detail="Invalid NSE/BSE symbol")
        try:
            return workspace.stock_detail(symbol, period=period)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Stock data temporarily unavailable") from exc

    @app.get("/workspace/paper-portfolio")
    def workspace_paper_portfolio() -> dict[str, Any]:
        try:
            return workspace.paper_portfolio()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Paper portfolio temporarily unavailable") from exc

    @app.get(
        "/workspace/kite-session",
        dependencies=[Depends(require_admin_api_key)],
    )
    def workspace_kite_session() -> dict[str, Any]:
        """Authenticated, read-only broker session without credential disclosure."""
        try:
            broker = workspace.provider_factory()._default_kite()
            connected = bool(broker.health().get("authenticated"))
        except Exception:
            connected = False
            broker = None
        if not connected or broker is None:
            return {
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
            positions = broker.positions()
            holdings = broker.holdings()
            orders = broker.orders()
            margins = broker.margins()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Kite authenticated session data temporarily unavailable",
            ) from exc
        return {
            "status": "ready",
            "authenticated": True,
            "read_only": True,
            "broker_orders_allowed": False,
            "positions": positions if isinstance(positions, dict) else {},
            "holdings": holdings if isinstance(holdings, list) else [],
            "orders": orders[-50:] if isinstance(orders, list) else [],
            "margins": margins if isinstance(margins, dict) else {},
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
