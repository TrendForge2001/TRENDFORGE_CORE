from __future__ import annotations

from database.database import Database
from database.migrations import backtest_results
from database.repositories.backtest_results import (
    BacktestResultsRepository,
)


def test_backtest_repository_round_trips_detailed_run(tmp_path):
    db = Database(str(tmp_path / "backtest.db"))
    try:
        backtest_results.migrate(db)
        repo = BacktestResultsRepository(db=db)

        saved = repo.save(
            {
                "run_id": "bt-1",
                "strategy_name": "EMA20_50_RSI",
                "strategy_version": "R68.4-v1",
                "status": "completed",
                "symbol": "TCS",
                "timeframe": "1d",
                "start_date": "2025-01-01",
                "end_date": "2026-01-01",
                "total_trades": 3,
                "win_rate": 66.67,
                "net_profit": 12000.0,
                "max_drawdown": 8.5,
                "sharpe_ratio": 1.4,
                "initial_capital": 100000.0,
                "final_capital": 112000.0,
                "return_pct": 12.0,
                "buy_hold_return_pct": 9.0,
                "profit_factor": 2.1,
                "expectancy": 4000.0,
                "exposure_pct": 45.0,
                "cost_bps": 5.0,
                "slippage_bps": 3.0,
                "parameters": {"period": "2y"},
                "result": {
                    "run_id": "bt-1",
                    "metrics": {"return_pct": 12.0},
                },
            }
        )

        assert saved["run_id"] == "bt-1"
        assert saved["parameters"]["period"] == "2y"
        assert saved["result"]["metrics"]["return_pct"] == 12.0

        loaded = repo.by_run_id("bt-1")
        assert loaded is not None
        assert loaded["strategy_version"] == "R68.4-v1"
        assert loaded["result"]["run_id"] == "bt-1"
    finally:
        db.close()


def test_backtest_repository_keeps_legacy_summary_save_compatible(
    tmp_path,
):
    db = Database(str(tmp_path / "backtest.db"))
    try:
        backtest_results.migrate(db)
        repo = BacktestResultsRepository(db=db)

        saved = repo.save(
            {
                "strategy_name": "legacy",
                "symbol": "TEST",
            }
        )

        assert saved["strategy_name"] == "legacy"
        assert saved["symbol"] == "TEST"
        assert repo.count() == 1
        assert repo.latest(1)[0]["parameters"] == {}
        assert repo.latest(1)[0]["result"] == {}
    finally:
        db.close()
