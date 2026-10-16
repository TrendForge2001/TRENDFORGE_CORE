"""Persist legacy summaries and detailed R68.4 backtest runs."""
from __future__ import annotations


def _columns(db):
    return {
        str(row["name"])
        for row in db.fetchall(
            "PRAGMA table_info(backtest_results)"
        )
    }


def migrate(db):
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS backtest_results(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            strategy_name TEXT,
            symbol TEXT,
            timeframe TEXT,
            start_date DATE,
            end_date DATE,
            total_trades INTEGER,
            win_rate REAL,
            net_profit REAL,
            max_drawdown REAL,
            sharpe_ratio REAL,
            created_at DATETIME
        )
        """
    )

    columns = _columns(db)
    additions = (
        (
            "run_id",
            "ALTER TABLE backtest_results ADD COLUMN run_id TEXT",
        ),
        (
            "strategy_version",
            "ALTER TABLE backtest_results "
            "ADD COLUMN strategy_version TEXT",
        ),
        (
            "status",
            "ALTER TABLE backtest_results ADD COLUMN status TEXT",
        ),
        (
            "initial_capital",
            "ALTER TABLE backtest_results "
            "ADD COLUMN initial_capital REAL",
        ),
        (
            "final_capital",
            "ALTER TABLE backtest_results "
            "ADD COLUMN final_capital REAL",
        ),
        (
            "return_pct",
            "ALTER TABLE backtest_results ADD COLUMN return_pct REAL",
        ),
        (
            "buy_hold_return_pct",
            "ALTER TABLE backtest_results "
            "ADD COLUMN buy_hold_return_pct REAL",
        ),
        (
            "profit_factor",
            "ALTER TABLE backtest_results "
            "ADD COLUMN profit_factor REAL",
        ),
        (
            "expectancy",
            "ALTER TABLE backtest_results ADD COLUMN expectancy REAL",
        ),
        (
            "exposure_pct",
            "ALTER TABLE backtest_results ADD COLUMN exposure_pct REAL",
        ),
        (
            "cost_bps",
            "ALTER TABLE backtest_results ADD COLUMN cost_bps REAL",
        ),
        (
            "slippage_bps",
            "ALTER TABLE backtest_results ADD COLUMN slippage_bps REAL",
        ),
        (
            "parameters_json",
            "ALTER TABLE backtest_results "
            "ADD COLUMN parameters_json TEXT",
        ),
        (
            "result_json",
            "ALTER TABLE backtest_results ADD COLUMN result_json TEXT",
        ),
    )

    for name, statement in additions:
        if name not in columns:
            db.execute(statement)

    db.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS
        idx_backtest_results_run_id
        ON backtest_results(run_id)
        WHERE run_id IS NOT NULL
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_backtest_results_symbol_created
        ON backtest_results(symbol, created_at DESC)
        """
    )
    db.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_backtest_results_strategy_created
        ON backtest_results(strategy_name, created_at DESC)
        """
    )
