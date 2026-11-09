"""Historical research only; shared by local and isolated workers."""

from services.portfolio_backtest_service import PortfolioBacktestService
from services.research_report import build_report


def execute_research(technical, batch_id, kind, request, progress):
    settings = request["settings"]
    if kind == "backtest":
        result = PortfolioBacktestService(technical).run(
            symbols=request["symbols"],
            mode=settings["mode"],
            strategy_id=settings["strategy_id"],
            period=settings["period"],
            short_borrow_available=request.get("short_borrow_available", False),
            run_id=batch_id,
            progress=progress,
            simulation_progress=lambda done, total: progress("simulation", done, total),
            report_horizon=request["horizon"],
            report_stock_list=request["stock_list"],
            max_candle_rows=request.get("max_candle_rows"),
        )
        report = result["report"]
    else:
        result = technical.scan(
            symbols=request["symbols"],
            mode=settings["mode"],
            strategy_id=settings["strategy_id"],
            period=settings["period"],
            top_n=len(request["symbols"]),
            execute_paper=False,
            run_id=batch_id,
            progress=progress,
        )
        report = build_report(
            result,
            kind="scan",
            horizon=request["horizon"],
            stock_list=request["stock_list"],
        )
    return report
