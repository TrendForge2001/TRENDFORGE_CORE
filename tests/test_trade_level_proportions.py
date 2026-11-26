"""Risk denominator provenance and signed geometry in backtest evidence."""

import pytest

from services.research_report import build_report
from services.workbench_export import trade_summary
from tests.test_compact_backtesting import partial_result


def test_report_uses_frozen_initial_stop_before_a_tightened_active_reference():
    result = partial_result()
    result["run_id"] = "original-risk"
    for trade in result["trades"]:
        trade.pop("initial_stoploss", None)
        trade["initial_stop"] = 95
        trade["stoploss"] = 109
    report = build_report(result, kind="backtest")
    assert all(row["initial_stoploss"] == 95 for row in report["rows"])
    assert all(row["initial_stop_basis"] == "initial" for row in report["rows"])
    assert report["metrics"]["net_profit"] == result["metrics"]["net_profit"]


def test_report_marks_a_legacy_active_stop_as_unverified_initial_risk():
    result = partial_result()
    result["run_id"] = "legacy-risk"
    for trade in result["trades"]:
        trade.pop("initial_stoploss", None)
        trade.pop("initial_stop", None)
        trade["stoploss"] = 99.99
    report = build_report(result, kind="backtest")
    assert all(
        row["initial_stop_basis"] == "unverified_legacy_stop" for row in report["rows"]
    )
    assert trade_summary(report["rows"])["Net R"] is None


@pytest.mark.parametrize(
    "side,stop,net,expected", [("LONG", 90, 20, 0.5), ("SHORT", 110, 12, 0.3)]
)
def test_excel_net_r_uses_the_original_quantity_and_direction(
    side, stop, net, expected
):
    fills = [
        {
            "symbol": "EXAMPLE",
            "side": side,
            "entry_price": 100,
            "initial_stoploss": stop,
            "entry_quantity": 4,
            "quantity": 2,
            "exit_price": 105,
            "net_pnl": net / 2,
            "entry_at": "2026-11-20",
            "exit_at": date,
        }
        for date in ("2026-11-23", "2026-11-25")
    ]
    assert trade_summary(fills)["Net R"] == expected


@pytest.mark.parametrize(
    "updates",
    [
        {"initial_stoploss": 110},
        {"initial_stoploss": 0},
        {"initial_stop_basis": "unverified_legacy_stop"},
        {"initial_stoploss": True},
    ],
)
def test_excel_never_manufactures_positive_risk_from_invalid_or_unknown_stops(updates):
    fill = {
        "symbol": "EXAMPLE",
        "side": "LONG",
        "entry_price": 100,
        "initial_stoploss": 90,
        "entry_quantity": 4,
        "quantity": 4,
        "exit_price": 105,
        "net_pnl": 20,
        **updates,
    }
    assert trade_summary([fill])["Net R"] is None
