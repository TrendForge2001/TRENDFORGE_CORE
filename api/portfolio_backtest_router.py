"""Admin-protected historical portfolio account; capital policy is server-owned."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from api.admin_auth import require_admin_api_key
from config.scanner_capacity import MAX_BACKTEST_SYMBOLS
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import TechnicalTradingValidationError


class PortfolioBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=MAX_BACKTEST_SYMBOLS)
    strategy_id: str = Field(min_length=1, max_length=80)
    mode: Literal["intraday", "swing", "positional"] = "swing"
    liquidity_confirmation: StrictBool = False
    short_borrow_available: StrictBool = False
    tick_size: float = Field(default=0.05, gt=0, le=100, allow_inf_nan=False)
    period: str | None = Field(default=None, max_length=10)
    cost_bps: float = Field(default=12, ge=0, le=1000, allow_inf_nan=False)
    slippage_bps: float = Field(default=5, ge=0, le=1000, allow_inf_nan=False)
    run_id: str | None = Field(default=None, min_length=1, max_length=120)


def portfolio_backtest_router(technical_getter):
    router = APIRouter(dependencies=[Depends(require_admin_api_key)])

    @router.post("/technical/portfolio-backtest")
    def run_portfolio(request: PortfolioBacktestRequest):
        try:
            return PortfolioBacktestService(technical_getter()).run(
                **request.model_dump()
            )
        except TechnicalTradingValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        except Exception:
            raise HTTPException(
                503, "Portfolio backtest is temporarily unavailable"
            ) from None

    return router
