"""Production checkpoint diagnosis preserves economics, privacy and controls."""

import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest

from scanner.approved_strategies import IDS
from scanner.strategy_registry import REGISTRY_VERSION
from services.validation_journal import ValidationJournal
from services.validation_trade_diagnostics import trade_diagnostics


@pytest.fixture
def saved(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "state.db"))
    snapshot = {
        "status": "completed",
        "run_id": "economic-review",
        "request": {},
        "registry_version": REGISTRY_VERSION,
    }
    journal = ValidationJournal(snapshot["run_id"], {}, REGISTRY_VERSION)
    membership = {"NIFTY 500": True}
    trade = {
        "strategy_id": IDS[0],
        "mode": "intraday",
        "symbol": "PRIVATE_SYMBOL",
        "membership": membership,
        "entry_price": 100,
        "quantity": 10,
        "risk_per_share": 2,
        "entry_at": "2026-11-18T10:00:00+05:30",
        "exit_at": "2026-11-18T10:15:00+05:30",
        "gross_pnl": 10,
        "transaction_costs": 2,
        "net_pnl": 8,
        "exit_reason": "STOPLOSS",
        "partial_taken": False,
        "private_field": "PRIVATE_PROVIDER_SECRET",
    }
    test = {
        "strategy_id": IDS[0],
        "mode": "intraday",
        "status": "completed",
        "membership": membership,
        "initial_capital": 100000,
        "total_trades": 2,
        "return_pct": 0.004,
        "net_profit": 4,
        "exposure_pct": 10,
        "max_capital_committed": 1000,
        "start_date": "2026-11-18T09:15:00+05:30",
        "end_date": "2026-11-18T15:15:00+05:30",
    }
    loss = {
        **trade,
        "entry_at": "2026-11-18T11:00:00+05:30",
        "exit_at": "2026-11-18T11:30:00+05:30",
        "gross_pnl": -2,
        "net_pnl": -4,
        "exit_reason": "PRIVATE_PROVIDER_ERROR",
    }
    journal.rows["backtests"].append(test)
    journal.rows["trades"].pending.extend([trade, loss])
    journal.commit_unit("intraday", "PRIVATE_SYMBOL")
    for symbol, traded, net in (
        ("IDLE", False, 0),
        ("FLAT", True, 0),
        ("LOSING", True, -4),
    ):
        journal.rows["backtests"].append(
            {
                **test,
                "total_trades": int(traded),
                "return_pct": net / 1000,
                "net_profit": net,
            }
        )
        if traded:
            journal.rows["trades"].append(
                {**trade, "gross_pnl": net + 2, "net_pnl": net}
            )
        journal.commit_unit("intraday", symbol)
    yield journal, snapshot
    journal.close()


def test_idle_flat_and_losing_stocks_are_distinct_and_cash_reconciles(saved):
    journal, snapshot = saved
    before = journal.path.read_bytes()
    report = trade_diagnostics(snapshot, "NIFTY 500")
    assert report["status"] == "available"
    assert len(report["rows"]) == 1
    row = report["rows"][0]
    assert row["counts"]["completed_symbols"] == 4
    assert row["counts"]["no_trade_symbols"] == 1
    assert row["counts"]["traded_symbols"] == 3
    assert row["counts"]["flat_symbols"] == 2
    assert row["counts"]["losing_symbols"] == 1
    assert row["counts"]["profitable_symbols"] == 1
    assert row["counts"]["additional_same_day_entries"] == 1
    assert row["counts"]["exits_within_15_minutes"] == 3
    assert row["mean_holding_minutes"] == 18.75
    assert row["traded_symbol_profitable_pct"] == 33.3333
    assert row["traded_symbol_median_return_pct"] == 0
    assert row["net_pnl"] == 0
    assert row["gross_pnl_before_fees"] - row["transaction_costs"] == 0
    assert row["trade_to_backtest_net_difference"] == 0
    assert journal.path.read_bytes() == before
    serialized = json.dumps(report)
    assert "PRIVATE" not in serialized and "IDLE" not in serialized
    assert row["exits"]["OTHER"]["fills"] == 1


def test_partial_profit_exit_legs_are_separate_from_final_exit_reason(saved):
    journal, snapshot = saved
    trade = {
        "strategy_id": IDS[0],
        "mode": "intraday",
        "membership": {"NIFTY 500": True},
        "entry_at": datetime(2026, 11, 18, 4, 30, tzinfo=UTC).isoformat(),
        "exit_at": "2026-11-18T12:00:00+05:30",
        "net_pnl": 30,
        "gross_pnl": 32,
        "transaction_costs": 2,
        "exit_reason": "R3_FINAL_TARGET",
        "partial_taken": True,
        "exit_legs": [
            {
                "exit_reason": "R1_PARTIAL_PROFIT",
                "net_pnl": 10,
                "gross_pnl": 11,
                "transaction_costs": 1,
            },
            {
                "exit_reason": "R3_FINAL_TARGET",
                "net_pnl": 20,
                "gross_pnl": 21,
                "transaction_costs": 1,
            },
        ],
    }
    journal.rows["trades"].append(trade)
    journal.commit_unit("intraday", "PARTIAL")
    row = trade_diagnostics(snapshot, "NIFTY 500")["rows"][0]
    # Trades without a completed backtest never enter an economic review.
    assert "R1_PARTIAL_PROFIT" not in row["exits"]
    journal.rows["trades"].append(trade)
    journal.rows["backtests"].append(
        {
            "strategy_id": IDS[0],
            "mode": "intraday",
            "status": "completed",
            "total_trades": 1,
            "membership": {"NIFTY 500": True},
            "net_profit": 30,
            "return_pct": 0.03,
        }
    )
    journal.commit_unit("intraday", "PARTIAL2")
    row = trade_diagnostics(snapshot, "NIFTY 500")["rows"][0]
    assert row["counts"]["partial_profit_trades"] == 1
    assert row["exits"]["R1_PARTIAL_PROFIT"] == {
        "fills": 1,
        "net_pnl": 10,
        "gross_pnl": 11,
        "transaction_costs": 1,
    }
    assert row["exits"]["R3_FINAL_TARGET"]["net_pnl"] == 20
    assert row["net_pnl"] == 30 and row["trade_to_backtest_net_difference"] == 0


@pytest.mark.parametrize(
    "change",
    [
        {"registry_version": "old"},
        {"request": {"changed": True}},
        {"run_id": "missing"},
        {"status": "running"},
    ],
)
def test_missing_stale_or_mismatched_checkpoints_cannot_leak_or_be_created(
    saved, change
):
    journal, snapshot = saved
    before = sorted(journal.path.parent.iterdir())
    report = trade_diagnostics({**deepcopy(snapshot), **change}, "NIFTY 500")
    assert report == {"status": "unavailable", "rows": []}
    assert sorted(journal.path.parent.iterdir()) == before


def test_other_universe_and_unknown_strategy_are_excluded(saved):
    journal, snapshot = saved
    journal.rows["backtests"].append(
        {
            "strategy_id": "PRIVATE_UNKNOWN_STRATEGY",
            "mode": "intraday",
            "status": "completed",
            "membership": {"NIFTY 500": True},
            "net_profit": 999999999,
        }
    )
    journal.commit_unit("intraday", "UNKNOWN")
    assert len(trade_diagnostics(snapshot, "NIFTY 500")["rows"]) == 1
    assert trade_diagnostics(snapshot, "NIFTY 100") == {
        "status": "available",
        "rows": [],
    }
