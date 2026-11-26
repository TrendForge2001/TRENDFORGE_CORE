"""Historical research only; shared by local and isolated workers."""

from datetime import datetime

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
            alignment_progress=lambda: progress("alignment", 0),
            report_horizon=request["horizon"],
            report_stock_list=request["stock_list"],
            max_candle_rows=request.get("max_candle_rows"),
            weekly_comparison=request.get("weekly_comparison", False),
            **{
                key: request[key]
                for key in (
                    "cost_bps",
                    "slippage_bps",
                    "initial_capital",
                    "risk_fraction",
                    "max_positions",
                    "move_stop_after_partial",
                )
                if request.get(key) is not None
            },
        )
        report = result["report"]
    else:
        progress("history", 0)
        cutoff = request.get("scan_cutoff")
        result = technical.scan(
            symbols=request["symbols"],
            mode=settings["mode"],
            strategy_id=settings["strategy_id"],
            period=settings["period"],
            top_n=len(request["symbols"]),
            execute_paper=False,
            notify_paper=False,
            **({"now": datetime.fromisoformat(cutoff)} if cutoff else {}),
            run_id=batch_id,
            progress=progress,
            horizon=request["horizon"],
        )
        progress("report", len(request["symbols"]))
        report = build_report(
            result,
            kind="scan",
            horizon=request["horizon"],
            stock_list=request["stock_list"],
        )
    return report
