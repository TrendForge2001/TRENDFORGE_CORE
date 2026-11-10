"""Compact trading-workspace routes for the R72.3 unified webapp."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal
from urllib.parse import unquote

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

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


class KitePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=r"^[A-Z0-9][A-Z0-9._&-]{0,29}$")
    side: Literal["BUY", "SHORT"]
    product: Literal["MIS", "CNC"]
    quantity: StrictInt = Field(ge=1, le=1_000_000)
    stoploss: float = Field(gt=0, le=1e8, allow_inf_nan=False)
    target: float = Field(gt=0, le=1e8, allow_inf_nan=False)


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
            raise HTTPException(
                status_code=503, detail="Index constituents temporarily unavailable"
            ) from exc

    @app.get("/workspace/watchlist/{index_name}")
    def workspace_watchlist(index_name: str) -> dict[str, Any]:
        try:
            return workspace.watchlist(unquote(index_name))
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Watchlist temporarily unavailable"
            ) from exc

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
            raise HTTPException(
                status_code=503, detail="Stock data temporarily unavailable"
            ) from exc

    @app.get("/workspace/paper-portfolio")
    def workspace_paper_portfolio() -> dict[str, Any]:
        try:
            return workspace.paper_portfolio()
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="Paper portfolio temporarily unavailable"
            ) from exc

    @app.get(
        "/workspace/kite-session",
        dependencies=[Depends(require_admin_api_key)],
    )
    def workspace_kite_session() -> dict[str, Any]:
        """Authenticated, read-only broker session without credential disclosure."""
        try:
            return workspace.kite_session()
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Kite authenticated session data temporarily unavailable",
            ) from exc

    @app.get(
        "/workspace/kite-trading-readiness",
        dependencies=[Depends(require_admin_api_key)],
    )
    def kite_execution_readiness(
        probe_quotes: bool = False, probe_history: bool = False
    ) -> dict[str, Any]:
        try:
            from services.kite_trading_readiness import kite_trading_readiness

            return kite_trading_readiness(
                workspace.provider_factory()._default_kite(),
                probe_quotes=probe_quotes,
                probe_history=probe_history,
            )
        except Exception:
            raise HTTPException(503, "Kite trading readiness is unavailable") from None

    @app.get(
        "/workspace/kite-network-readiness",
        dependencies=[Depends(require_admin_api_key)],
    )
    def kite_network_status(response: Response, probe: bool = False):
        from services.kite_network_readiness import kite_network_readiness

        response.headers["Cache-Control"] = "no-store"
        try:
            return kite_network_readiness(probe=probe)
        except Exception:
            raise HTTPException(503, "Kite network check is unavailable") from None

    @app.get("/workspace/technical/auto-status")
    def workspace_auto_status() -> dict[str, Any]:
        runner = auto_scanner()
        if runner is None:
            return {"status": "not_supported"}
        return runner.status()

    @app.post(
        "/workspace/kite/order-preview", dependencies=[Depends(require_admin_api_key)]
    )
    def kite_order_preview(request: KitePreviewRequest, response: Response):
        from services.kite_market_preflight import PreflightInputError, preview_order

        response.headers["Cache-Control"] = "no-store"
        try:
            return preview_order(
                workspace.provider_factory()._default_kite(), **request.model_dump()
            )
        except PreflightInputError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(503, "Kite preview inputs are unavailable") from None

    @app.get(
        "/workspace/scan-data-readiness", dependencies=[Depends(require_admin_api_key)]
    )
    def scanner_data_readiness(
        response: Response,
        symbols: list[str] = Query(
            default=["BIRET", "DUMMYHEG", "HFCL"], min_length=1, max_length=10
        ),
        mode: Literal["intraday", "swing", "positional"] = "swing",
        period: Literal["30d", "45d", "60d", "1y", "2y", "5y"] = "2y",
        strategy_id: str | None = None,
    ):
        from services.kite_market_preflight import scanner_input_checks

        response.headers["Cache-Control"] = "no-store"
        try:
            return scanner_input_checks(
                workspace.provider_factory()._default_kite(),
                symbols=symbols,
                mode=mode,
                period=period,
                strategy_id=strategy_id,
            )
        except (ValueError, KeyError):
            raise HTTPException(
                422, "Choose valid scanner symbols, mode, history and strategy"
            ) from None
        except Exception:
            raise HTTPException(503, "Scanner input checks are unavailable") from None

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
