"""Private stock report reads; this router never starts trading or writes orders."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from api.admin_auth import require_admin_api_key
from services.stock_report_service import StockReportService


def stock_report_router(
    technical_getter,
    *,
    company_provider=None,
    news_getter=None,
    market_label="Kite Connect",
):
    router = APIRouter(
        prefix="/reports/stocks", dependencies=[Depends(require_admin_api_key)]
    )
    service = StockReportService(
        technical_getter,
        company_provider=company_provider,
        news_getter=news_getter,
        market_label=market_label,
    )

    @router.get("/{symbol}")
    def stock_report(
        symbol: str,
        horizon: Literal["short_term", "long_term"] = "short_term",
        strategy_id: str | None = None,
        refresh: bool = False,
    ):
        try:
            return service.build(
                symbol, horizon=horizon, strategy_id=strategy_id, force_refresh=refresh
            )
        except ValueError:
            raise HTTPException(422, "Invalid stock or strategy selection") from None
        except Exception:
            raise HTTPException(
                503, "Stock report is temporarily unavailable"
            ) from None

    return router
