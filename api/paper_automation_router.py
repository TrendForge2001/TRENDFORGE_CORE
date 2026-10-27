"""Authenticated operator controls and strategy paper accounting."""

from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from api.admin_auth import require_admin_api_key
from services.strategy_paper_reporting import StrategyPaperReporting


class AutomationControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    universe: Literal["NIFTY 100", "NIFTY 200", "NIFTY 500"] = "NIFTY 100"
    symbols: list[str] | None = Field(default=None, min_length=1, max_length=100)
    strategy_ids: list[str] | None = Field(default=None, min_length=1, max_length=6)


def paper_automation_router(
    *, automation_getter: Callable, paper_getter: Callable
) -> APIRouter:
    router = APIRouter(prefix="/paper", dependencies=[Depends(require_admin_api_key)])

    def automation():
        try:
            service = automation_getter()
        except Exception:
            service = None
        if service is None:
            raise HTTPException(503, "Saved-strategy paper automation is unavailable")
        return service

    @router.get("/automation")
    def automation_status() -> dict[str, Any]:
        try:
            return automation().status()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, "Paper automation status is unavailable") from None

    @router.put("/automation")
    def automation_control(request: AutomationControl) -> dict[str, Any]:
        try:
            return automation().configure(**request.model_dump(exclude_unset=True))
        except HTTPException:
            raise
        except ValueError:
            raise HTTPException(
                422,
                "Invalid paper target: choose up to 100 stocks from the selected "
                "Nifty validation universe and executable source strategies",
            ) from None
        except Exception:
            raise HTTPException(
                503, "Paper automation settings could not be saved"
            ) from None

    @router.get("/strategy-pnl")
    def strategy_pnl(
        period: Literal["daily", "weekly", "monthly", "yearly", "all"] = "daily",
    ) -> dict[str, Any]:
        try:
            paper = paper_getter()
            if paper is None:
                raise ValueError("Unavailable")
            return StrategyPaperReporting(paper).statement(period=period)
        except Exception:
            raise HTTPException(503, "Strategy paper P&L is unavailable") from None

    return router
