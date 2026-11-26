"""Private stock report reads; this router never starts trading or writes orders."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from api.admin_auth import require_admin_api_key
from services.conditional_stock_plan import display_plan
from services.stock_report_service import StockReportService, paper_review_allowed


def stock_report_router(
    technical_getter,
    *,
    company_provider=None,
    news_getter=None,
    market_label="Kite Connect",
    quote_getter=None,
):
    router = APIRouter(
        prefix="/reports/stocks", dependencies=[Depends(require_admin_api_key)]
    )
    service = StockReportService(
        technical_getter,
        company_provider=company_provider,
        news_getter=news_getter,
        market_label=market_label,
        quote_getter=quote_getter,
    )

    def load(symbol, horizon, strategy_id, refresh=False):
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

    @router.get("/{symbol}")
    def stock_report(
        symbol: str,
        horizon: Literal["short_term", "long_term"] = "short_term",
        strategy_id: str | None = None,
        refresh: bool = False,
    ):
        report = load(symbol, horizon, strategy_id, refresh)
        return {
            **report,
            "display_plan": display_plan(report),
            "paper_review_available": paper_review_allowed(report),
        }

    @router.get("/{symbol}/report.html")
    def stock_report_html(
        symbol: str,
        horizon: Literal["short_term", "long_term"] = "short_term",
        strategy_id: str | None = None,
    ):
        from webapp.stock_report_document import document

        report = load(symbol, horizon, strategy_id)
        filename = f"{report['symbol']}_TrendForge_Report.html"
        return Response(
            document(report),
            media_type="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
