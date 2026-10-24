"""IST timestamps and reconciled independent-allocation backtest accounting."""

from copy import deepcopy
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest

from webapp.backtest_pnl import build_backtest_pnl
from webapp.paper_excel import paper_daily_xlsx, safe_csv_bytes
from webapp.trade_timestamps import (
    display_market_time,
    export_trade_frame,
    format_trade_frame,
    market_timestamp,
)


def result(symbol="TCS", initial=100.0, profit=10.0, start="2026-10-01T00:00:00Z"):
    return {
        "status": "completed",
        "symbol": symbol,
        "interval": "1d",
        "strategy": {"name": "Technical Momentum"},
        "metrics": {
            "initial_capital": initial,
            "final_capital": initial + profit,
            "net_profit": profit,
            "total_trades": 1,
            "transaction_costs": 0.0,
            "slippage_impact_estimate": 0.0,
        },
        "trades": [
            {
                "entry_at": "2026-10-01T09:30:00+05:30",
                "exit_at": "2026-10-02T20:00:00Z",
                "net_pnl": profit,
                "gross_pnl": profit,
                "transaction_costs": 0.0,
            }
        ],
        "equity_curve": [
            {"date": start, "equity": initial},
            {"date": "2026-10-03T00:00:00Z", "equity": initial + profit},
        ],
    }


def test_aware_naive_and_missing_timestamps_have_unambiguous_ist_presentation():
    assert display_market_time("2026-10-23T20:15:16Z") == "24 Oct 2026, 01:45:16 IST"
    assert display_market_time("2026-10-24 09:30:00") == "24 Oct 2026, 09:30:00 IST"
    assert (
        display_market_time("2026-10-24T09:30:00+05:30") == "24 Oct 2026, 09:30:00 IST"
    )
    for value in [None, pd.NaT, pd.NA, float("nan"), ""]:
        assert display_market_time(value) == "—"
    for value in ["03/04/2026", "bad", 0, True, {}, []]:
        assert display_market_time(value) == "Invalid timestamp"
    assert market_timestamp("2026-10-23T20:00:00Z").date().isoformat() == "2026-10-24"


def test_daily_bars_do_not_claim_exact_fill_times_and_raw_export_evidence_survives():
    assert (
        display_market_time("2026-10-24T00:00:00+05:30", daily=True)
        == "24 Oct 2026 (daily bar, IST)"
    )
    assert display_market_time("2026-10-24") == "24 Oct 2026 (time unavailable)"
    source = pd.DataFrame(
        {
            "entry_at": ["2026-10-23T20:15:16.123456Z"],
            "exit_at": [None],
            "net_pnl": [-12.5],
        }
    )
    original = source.copy(deep=True)
    displayed = format_trade_frame(source)
    assert displayed.iloc[0]["entry_at"] == "24 Oct 2026, 01:45:16 IST"
    exported = export_trade_frame(source)
    assert exported.iloc[0]["entry_at"] == source.iloc[0]["entry_at"]
    assert exported.iloc[0]["entry_at_ist"] == displayed.iloc[0]["entry_at"]
    assert exported.iloc[0]["exit_at_ist"] == "—"
    assert exported.iloc[0]["net_pnl"] == -12.5
    pd.testing.assert_frame_equal(source, original)
    pd.testing.assert_frame_equal(export_trade_frame(exported), exported)
    assert "entry_at_ist" in safe_csv_bytes(source).decode("utf-8-sig")


def test_paper_excel_keeps_raw_entry_exit_and_adds_ist_columns():
    statement = {
        "scope": "paper_trading_closed_trades",
        "period": "daily",
        "period_end": "2026-10-24T10:00:00Z",
        "summary": {
            "trade_count": 1,
            "gross_profit": 10,
            "gross_loss": 0,
            "net_pnl": 10,
        },
        "trades": [
            {
                "created_at": "2026-10-23T20:00:00Z",
                "closed_at": "2026-10-24T03:30:00Z",
                "pnl": 10,
            }
        ],
        "daily": [],
    }
    book = load_workbook(BytesIO(paper_daily_xlsx(statement, {"positions": []})))
    values = list(book["Daily Closed Trades"].values)
    row = dict(zip(values[0], values[1], strict=True))
    assert row["created_at"] == "2026-10-23T20:00:00Z"
    assert row["created_at_ist"] == "24 Oct 2026, 01:30:00 IST"
    assert row["closed_at_ist"] == "24 Oct 2026, 09:00:00 IST"
    assert row["pnl"] == 10


def test_combined_pnl_weights_capital_and_aligns_missing_market_dates():
    runs = [result(), result("SBIN", 200, -20, "2026-10-02T00:00:00Z")]
    original = deepcopy(runs)
    report = build_backtest_pnl(runs)
    assert report["capital"] == 300
    assert report["final"] == 290
    assert report["net"] == -10
    assert report["return_pct"] == pytest.approx(-3.3333333)
    assert report["max_drawdown"] == pytest.approx(3.3333333)
    assert report["curve"]["Equity (₹)"].tolist() == [300, 300, 290]
    assert report["daily"].to_dict("records") == [
        {
            "Exit date (IST)": "2026-10-03",
            "Net P&L (₹)": -10,
            "Cumulative realized P&L (₹)": -10,
        }
    ]
    assert report["win_rate"] == 50
    assert report["profit_factor"] == 0.5
    assert report["fees"] == 0
    assert runs == original


def test_net_pnl_already_contains_fees_and_slippage_is_not_deducted_twice():
    run = result(profit=8)
    run["trades"][0].update(gross_pnl=10, transaction_costs=2)
    run["metrics"].update(transaction_costs=2, slippage_impact_estimate=3)
    report = build_backtest_pnl([run])
    assert report["net"] == 8
    assert report["fees"] == 2
    assert report["slippage"] == 3


@pytest.mark.parametrize(
    "broken", ["capital", "count", "net", "nan", "failed", "ledger"]
)
def test_inconsistent_financial_evidence_cannot_become_a_zero_pnl_dashboard(broken):
    run = result()
    if broken == "capital":
        run["metrics"]["final_capital"] = 99
    elif broken == "count":
        run["metrics"]["total_trades"] = 2
    elif broken == "net":
        run["trades"][0]["net_pnl"] = 0
    elif broken == "nan":
        run["metrics"]["net_profit"] = float("nan")
    elif broken == "failed":
        run["status"] = "failed"
    else:
        run["trades"] = ["invalid"]
    with pytest.raises(ValueError):
        build_backtest_pnl([run])


def test_unknown_exit_dates_and_incomplete_curves_are_explicitly_unavailable():
    run = result()
    run["trades"][0]["exit_at"] = "invalid"
    run["equity_curve"] = []
    report = build_backtest_pnl([run])
    assert report["net"] == 10
    assert report["daily"].empty
    assert report["curve"].empty
    assert report["max_drawdown"] is None
    assert report["warnings"]
    run["trades"][0]["exit_at"] = "2026-09-01T10:00:00+05:30"
    assert any(
        "exit precedes entry" in text for text in build_backtest_pnl([run])["warnings"]
    )


def test_empty_backtest_reports_zero_activity_with_capital_preserved():
    run = result(profit=0)
    run["trades"] = []
    run["metrics"]["total_trades"] = 0
    report = build_backtest_pnl([run])
    assert report["net"] == 0
    assert report["daily"].empty
    assert report["profit_factor"] is None
    assert report["win_rate"] == 0


def test_dashboard_stock_selector_renders_charts_and_changes_pnl():
    source = """
from webapp.backtest_pnl import render_backtest_pnl
from test_backtest_pnl_dashboard import result
render_backtest_pnl([result(), result("SBIN", 200, -20)], key="test", failed=1)
"""
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert (
        next(m for m in app.metric if m.label == "Net backtest P&L").value == "₹-10.00"
    )
    assert any("failed stock simulations" in w.value for w in app.warning)
    app.selectbox[0].set_value(0).run(timeout=15)
    assert not app.exception
    assert (
        next(m for m in app.metric if m.label == "Net backtest P&L").value == "₹10.00"
    )
