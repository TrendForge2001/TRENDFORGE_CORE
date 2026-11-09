"""Minimal controls, real exit accounting, full cash availability and list scope."""

from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from scanner.strategy_horizons import horizon_strategies
from services.portfolio_backtest_service import PortfolioBacktestService
from tests.test_three_stock_portfolio import frame, service, simulate
from webapp.api_client import ApiError
from webapp.backtest_trade_report import trade_report, validate_result

ROOT = Path(__file__).resolve().parents[1]


def partial_result():
    entry = {
        "symbol": "TCS",
        "side": "LONG",
        "entry_at": "2026-01-05T09:30:00+05:30",
        "entry_price": 100.0,
        "quantity": 10,
        "exit_at": "2026-01-07T10:00:00+05:30",
        "exit_price": 120.0,
        "exit_reason": "FINAL_TARGET",
        "transaction_costs": 2.0,
        "net_pnl": 148.0,
    }
    first = {
        **entry,
        "quantity": 5,
        "exit_at": "2026-01-06T10:00:00+05:30",
        "exit_price": 110.0,
        "exit_reason": "PARTIAL_PROFIT",
        "transaction_costs": 1.0,
        "net_pnl": 49.0,
    }
    second = {**entry, "quantity": 5, "transaction_costs": 1.0, "net_pnl": 99.0}
    return {
        "status": "completed",
        "interval": "1d",
        "parameters": {
            "deployment_limit": 100000,
            "cash_reserve": 0,
            "max_positions": 3,
        },
        "metrics": {
            "initial_capital": 100000,
            "final_capital": 100148,
            "net_profit": 148,
            "return_pct": 0.148,
            "max_drawdown_pct": 0,
            "total_trades": 1,
        },
        "trades": [entry],
        "exit_fills": [first, second],
        "equity_curve": [
            {
                "date": entry["exit_at"],
                "equity": 100148,
                "cash": 100148,
                "capital_committed": 0,
                "open_positions": 0,
            }
        ],
    }


def test_partial_exits_keep_both_actual_prices_quantities_and_allocated_costs():
    result = partial_result()
    ledger = trade_report(result)
    assert len(ledger) == 2
    assert ledger["entry_quantity"].tolist() == [10, 10]
    assert ledger["quantity"].tolist() == [5, 5]
    assert ledger["exit_price"].tolist() == [110, 120]
    assert ledger["trade_number"].tolist() == [1, 1]
    assert ledger["transaction_costs"].sum() == 2
    assert ledger["net_pnl"].sum() == 148
    assert not any(column.startswith("indicator_") for column in ledger)


@pytest.mark.parametrize(
    "damage",
    [
        "missing_leg",
        "duplicate_leg",
        "bad_quantity",
        "wrong_entry",
        "wrong_cost",
        "wrong_pnl",
        "missing_exit_time",
        "old_reserve",
    ],
)
def test_report_rejects_incomplete_or_inconsistent_execution_evidence(damage):
    result = partial_result()
    if damage == "missing_leg":
        result["exit_fills"].pop()
    elif damage == "duplicate_leg":
        result["exit_fills"].append(deepcopy(result["exit_fills"][0]))
    elif damage == "bad_quantity":
        result["exit_fills"][0].update(quantity=4, net_pnl=39)
    elif damage == "wrong_entry":
        result["exit_fills"][0]["entry_at"] = "2026-01-04T09:30:00+05:30"
    elif damage == "wrong_cost":
        result["exit_fills"][0]["transaction_costs"] = -1
    elif damage == "wrong_pnl":
        result["exit_fills"][0]["net_pnl"] = 500
    elif damage == "missing_exit_time":
        result["trades"][0].pop("exit_at")
    else:
        result["parameters"].update(deployment_limit=80000, cash_reserve=20000)
    with pytest.raises(ApiError):
        validate_result(result)


def test_whole_initial_capital_is_available_with_no_reserve():
    result = simulate({"TCS": frame()})
    assert result["metrics"]["cash_reserve"] == 0
    assert result["metrics"]["deployment_limit"] == 100000
    assert result["metrics"]["max_capital_committed"] > 99000
    assert 0 <= result["metrics"]["minimum_cash"] < 102


def test_full_list_above_previous_hundred_stock_limit_is_batched_without_truncation():
    technical = service()
    original = technical.market_data.batch_candles_with_errors
    batches = []

    def batch(symbols, **kwargs):
        batches.append(list(symbols))
        return original(symbols, **kwargs)

    technical.market_data.batch_candles_with_errors = batch
    symbols = [f"NSE{i}" for i in range(101)]
    result = PortfolioBacktestService(technical).run(
        symbols=symbols, mode="swing", strategy_id="tf_swing_ema20_50_rsi_volume"
    )
    assert [symbol for group in batches for symbol in group] == symbols
    assert max(map(len, batches)) <= 25
    assert set(result["symbols"]) == set(symbols)
    assert result["parameters"]["cash_reserve"] == 0
    validate_result(result)


class Client:
    def __init__(self):
        self.calls = []

    def get_json(self, path, **kwargs):
        return {"rows": [{"symbol": "TCS"}, {"symbol": "SBIN"}]}

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        return {"batch_id": "batch-" + str(len(self.calls)), "status": "queued"}


def open_page(monkeypatch):
    client = Client()
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(ROOT / "webapp/pages/kite_backtesting.py").run(timeout=15)
    assert not app.exception
    return app, client


def test_page_has_only_two_selectors_two_actions_and_actual_entry_exit_report(
    monkeypatch,
):
    app, client = open_page(monkeypatch)
    assert [item.label for item in app.selectbox] == [
        "Short Swing strategy",
        "Stock list",
        "Backtesting period",
    ]
    assert [item.label for item in app.tabs] == [
        "Intraday",
        "Short Swing",
        "Short Term",
        "Medium Term",
        "Long Term",
    ]
    assert [item.label for item in app.button] == ["Scan stocks", "Backtest"]
    assert (
        not app.radio
        and not app.checkbox
        and not app.multiselect
        and not app.number_input
    )
    assert not app.dataframe
    app.button[0].click().run(timeout=15)
    assert not app.exception and not app.dataframe
    assert client.calls[-1][0] == "/reports/scan"
    app.button[1].click().run(timeout=15)
    assert not app.exception and not app.metric and not app.dataframe
    assert client.calls[-1][0] == "/reports/backtest"
    assert client.calls[-1][1]["symbols"] == ["TCS", "SBIN"]
    app.selectbox[2].set_value("1y").run(timeout=15)
    assert not app.success
    app.button[1].click().run(timeout=15)
    assert client.calls[-1][1]["period"] == "1y"
    assert app.session_state["tf_report_selected_batch"] == "batch-3"
    assert any("Reports" in item.value for item in app.success)
    app.selectbox[1].set_value("NIFTY PHARMA").run(timeout=15)
    assert not app.exception and not app.success


def test_bearish_strategy_carries_visible_borrow_assumption_without_extra_controls(
    monkeypatch,
):
    app, client = open_page(monkeypatch)
    label = next(
        label
        for label, row in horizon_strategies("short_swing").items()
        if row["short_borrow_available"]
    )
    assert "borrow assumed" in label
    app.selectbox[0].set_value(label).run(timeout=15)
    app.button[1].click().run(timeout=15)
    assert not app.exception
    assert client.calls[-1][1]["short_borrow_available"] is True
    assert not app.checkbox and len(app.selectbox) == 3
