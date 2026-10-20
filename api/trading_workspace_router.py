"""Compact trading-workspace routes for the R72.3 unified webapp."""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException
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
) -> None:
    workspace = TradingWorkspaceService(
        intelligence_getter=intelligence_getter,
        paper_getter=paper_getter,
    )

    def auto_scanner():
        return getattr(app.state, "technical_auto_scanner", None)

    @app.get("/workspace/watchlist/{index_name}")
    def workspace_watchlist(index_name: str) -> dict[str, Any]:
        try:
            return workspace.watchlist(unquote(index_name))
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/workspace/stock/{symbol}")
    def workspace_stock_detail(
        symbol: str,
        period: str = "6mo",
    ) -> dict[str, Any]:
        try:
            return workspace.stock_detail(symbol, period=period)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.get("/workspace/paper-portfolio")
    def workspace_paper_portfolio() -> dict[str, Any]:
        try:
            return workspace.paper_portfolio()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

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
