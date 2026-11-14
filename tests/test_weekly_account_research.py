"""Numerical admission boundaries, sparse histories and reconciled comparisons."""

import base64
from copy import deepcopy
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from backtest.weekly_account_engine import simulate_account
from scanner.weekly_account_policy import COMPARISONS, net_bracket
from scanner.weekly_floor import INDICATORS, STRATEGY_ID
from services.execution_report import ReportValidationError, validate_result
from services.weekly_floor_research import WeeklyFloorResearch
from tests import test_weekly_floor_research as weekly_support
from tests.support.weekly_floor_candles import NOW

technical = weekly_support.technical


def inputs(*, stop=930, target=1200, symbols=("A",), dates=None):
    dates = dates or ["2026-03-30T09:15:00+05:30", "2026-03-31T09:15:00+05:30"]
    frame = pd.DataFrame(
        {
            "open": 1000.0,
            "high": 1010.0,
            "low": 990.0,
            "close": 1000.0,
            "volume": 1000.0,
        },
        index=pd.DatetimeIndex(dates),
    )
    row = {k: 1.0 for k in INDICATORS}
    row.update(
        open=max(980.0, stop + 0.5),
        high=1011.0,
        low=stop + 0.05,
        close=1010.0,
        volume=200.0,
        EMA_50=970.0,
        EMA_100=960.0,
        RSI_WILDER_14=60.0,
        MACD=2.0,
        MACD_SIGNAL=1.0,
        VOL_EMA_30=100.0,
        PREVIOUS_CLOSE=1000.0,
        PREVIOUS_BODY_MIDPOINT=990.0,
        WEEKLY_WARMUP=100,
        FLOOR_YEAR_R2=target,
    )
    weeks = pd.DataFrame([row], index=pd.DatetimeIndex(["2026-03-29T23:59:59+05:30"]))
    levels = {2026: {k: row[k] for k in INDICATORS if k.startswith("FLOOR_YEAR_")}}
    return (
        {s: frame.copy() for s in symbols},
        {s: weeks.copy() for s in symbols},
        {s: levels for s in symbols},
    )


def test_cost_aware_one_percent_risk_sizes_example_below_fourteen_shares():
    result = simulate_account(*inputs(), COMPARISONS[1])
    entry = result["allocations"][0]
    assert entry["quantity"] == 13
    assert entry["planned_open_risk"] <= 1000
    assert entry["planned_risk_per_share"] == pytest.approx(
        1000.5 * 1.0012 - 930 * 0.9995 * 0.9988
    )
    assert result["trades"][0]["stoploss"] == 930
    assert result["trades"][0]["target2"] == 1200


def test_one_signal_cannot_consume_the_account():
    result = simulate_account(*inputs(stop=999), COMPARISONS[1])
    row = result["allocations"][0]
    assert row["quantity"] == 33
    assert row["notional"] <= 0.3333 * row["equity_before_entry"]
    assert result["equity_curve"][0]["cash"] > 66000


def test_three_positions_and_one_cash_book_across_one_hundred_stocks():
    result = simulate_account(
        *inputs(symbols=tuple(f"S{i:03d}" for i in range(100))), COMPARISONS[1]
    )
    assert len(result["allocations"]) == 3
    assert result["metrics"]["max_observed_positions"] == 3
    assert result["metrics"]["minimum_cash"] >= 0
    assert result["metrics"]["skip_reasons"] == {"position_limit": 97}
    for row in result["allocations"]:
        assert (
            row["planned_open_risk"] + row["existing_open_risk"]
            <= 0.03 * row["equity_before_entry"]
        )
    assert sum(t["net_pnl"] for t in result["trades"]) == pytest.approx(
        result["metrics"]["net_profit"]
    )


def test_stop_filter_uses_actual_slipped_fill_and_preserves_structural_stop():
    # Raw entry 1000 and stop 900 would be exactly 10%; slipped fill fails.
    data = inputs(stop=900)
    without = simulate_account(*data, COMPARISONS[1])
    filtered = simulate_account(*data, COMPARISONS[2])
    assert without["trades"][0]["initial_stoploss"] == 900
    assert not filtered["trades"]
    assert filtered["rejected_entries"][0]["reason"] == "stop_distance_above_10pct"


def test_reward_filter_is_net_of_costs_not_gross_price_ratio():
    data = inputs(stop=930, target=1107)
    fill = 1000 * 1.0005
    assert (1107 - fill) / (fill - 930) > 1.5
    assert net_bracket(fill, 930, 1107, 0.0012, 0.0005)["net_reward_risk"] < 1.5
    assert simulate_account(*data, COMPARISONS[2])["trades"]
    result = simulate_account(*data, COMPARISONS[3])
    assert not result["trades"]
    assert result["rejected_entries"][0]["reason"] == "net_reward_risk_below_1_5"


def test_new_listing_does_not_truncate_established_stock_or_enter_before_warmup():
    frames, weeks, annual = inputs(symbols=("OLD", "NEW"))
    older = frames["OLD"].iloc[:1].copy()
    older.index = pd.DatetimeIndex(["2026-01-01T09:15:00+05:30"])
    frames["OLD"] = pd.concat([older, frames["OLD"]])
    weeks["NEW"]["WEEKLY_WARMUP"] = 99
    result = simulate_account(frames, weeks, annual, COMPARISONS[1])
    assert result["start_date"].startswith("2026-01-01")
    assert [t["symbol"] for t in result["trades"]] == ["OLD"]


def test_absent_stock_bar_does_not_create_a_stop_fill_or_backfill_a_quote():
    frames, weeks, annual = inputs(symbols=("A", "B"))
    frames["A"] = frames["A"].iloc[:1]
    result = simulate_account(frames, weeks, annual, COMPARISONS[1])
    assert result["equity_curve"][-1]["stale_mark_symbols"] == ["A"]
    a = next(t for t in result["trades"] if t["symbol"] == "A")
    assert a["exit_reason"] == "END_OF_TEST"
    assert a["exit_mark_stale_days"] == 1
    assert result["metrics"]["final_equity_before_terminal"] - result["metrics"][
        "final_capital"
    ] == pytest.approx(result["metrics"]["terminal_liquidation_drag"])


def test_opening_gap_can_exceed_planned_risk_without_widening_stop():
    frames, weeks, annual = inputs()
    frames["A"].iloc[1, :4] = [880, 890, 870, 880]
    result = simulate_account(frames, weeks, annual, COMPARISONS[1])
    trade = result["trades"][0]
    assert trade["exit_reason"] == "STOP_GAP"
    assert trade["stoploss"] == 930
    assert -trade["net_pnl"] > trade["planned_open_risk"]


def test_comparison_service_persists_all_ledgers_and_workbook_tables(technical):
    class Market(type(technical.market_data)):
        def candles(self, symbol, **kwargs):
            assert symbol == "NIFTY 100"
            return self.frame.copy()

    technical.market_data = Market()
    result = WeeklyFloorResearch(technical).backtest(
        symbols=["EXAMPLE"], mode="positional", period="2y", now=NOW, comparison=True
    )
    assert [r["variant"] for r in result["comparisons"]] == [
        p.variant for p in COMPARISONS
    ]
    validate_result(result)
    assert result["benchmark"]["status"] == "complete"
    assert result["history_alignment"]["method"] == "per_stock_history_union_calendar"
    assert result["report"]["comparisons"] == result["comparisons"]
    book = load_workbook(
        BytesIO(base64.b64decode(result["report"]["xlsx_base64"])), read_only=True
    )
    assert {
        "Comparisons",
        "Daily account equity",
        "Entry risk audit",
        "Skipped entries",
        "Terminal liquidations",
        "Benchmark",
        "Stock coverage",
    } <= set(book.sheetnames)
    book.close()
    assert technical.repository.by_run_id(result["run_id"])["result"] == result
    damaged = deepcopy(result)
    damaged["allocations"][0]["planned_open_risk"] = 100000
    with pytest.raises(ReportValidationError):
        validate_result(damaged)


def test_render_keeps_nifty100_in_one_job_and_reserves_full_candle_budget(
    technical, monkeypatch
):
    from services.research_batches import ResearchBatchManager

    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(
        "services.weekly_floor_research.local_now", lambda now=None: NOW
    )
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        request = {
            "symbols": [f"S{i:03d}" for i in range(100)],
            "strategy_id": STRATEGY_ID,
            "stock_list": "NIFTY 100",
            "horizon": "long_term",
            "period": "2y",
        }
        batch = manager.submit("backtest", request)
        manager.futures[batch["batch_id"]].result(timeout=90)
        saved = manager.repository.get(batch["batch_id"])
        assert saved["status"] == "completed", saved.get("error_code")
        assert "partitions" not in saved["request"]
        assert saved["request"]["max_candle_rows"] == 150000
        assert len(saved["report"]["comparisons"]) == 4
        with pytest.raises(ValueError, match="compute limit"):
            manager.submit(
                "backtest", {**request, "symbols": [f"S{i:03d}" for i in range(500)]}
            )
    finally:
        manager.close(wait=True)


def test_shared_baseline_matches_existing_sizing_on_identical_calendars():
    from backtest.weekly_floor_engine import simulate_weekly
    from tests.test_weekly_floor_research import prepared

    daily, weekly, annual = prepared()
    frames, weeks, years = {"A": daily}, {"A": weekly}, {"A": annual}
    previous = simulate_weekly(frames, weeks, years)
    current = simulate_account(frames, weeks, years, COMPARISONS[0])
    assert current["metrics"]["net_profit"] == pytest.approx(
        previous["metrics"]["net_profit"]
    )
    assert [t["quantity"] for t in current["trades"]] == [
        t["quantity"] for t in previous["trades"]
    ]
    assert [t["exit_reason"] for t in current["trades"]] == [
        t["exit_reason"] for t in previous["trades"]
    ]


def test_history_service_retains_new_listing_without_shortening_old_history(technical):
    from tests.support.weekly_floor_candles import example_history

    original = example_history()

    class Market:
        def batch_candles_with_errors(self, symbols, **kwargs):
            return {
                s: original.iloc[-200:].copy() if s == "NEW" else original.copy()
                for s in symbols
            }, {}

    technical.market_data = Market()
    _, _, frames, _, _, errors, coverage = WeeklyFloorResearch(technical)._history(
        ["OLD", "NEW"],
        "positional",
        "5y",
        NOW,
        None,
        None,
        require_latest=False,
        full_daily=True,
    )
    assert not errors and len(frames["OLD"]) == len(original)
    assert len(frames["NEW"]) == 200
    assert (
        next(r for r in coverage if r["symbol"] == "NEW")["first_indicator_ready_week"]
        is None
    )


def test_future_close_cannot_finance_or_resize_an_earlier_open():
    frames, weeks, annual = inputs(symbols=("A", "B"))
    first = simulate_account(frames, weeks, annual, COMPARISONS[1])
    frames["A"].iloc[0, frames["A"].columns.get_loc("close")] = 5000
    changed = simulate_account(frames, weeks, annual, COMPARISONS[1])
    assert changed["allocations"] == first["allocations"]


def test_requested_window_does_not_delay_a_missed_entry_to_its_first_day():
    frames, weeks, annual = inputs()
    result = simulate_account(
        frames,
        weeks,
        annual,
        COMPARISONS[1],
        start=pd.Timestamp("2026-03-31T00:00:00+05:30"),
    )
    assert not result["trades"]  # Actual next open was March 30, outside window.


def test_tick_grid_stop_has_no_binary_floating_point_extra_tick():
    from scanner.weekly_floor import weekly_signal

    _, weeks, _ = inputs(stop=930)
    assert weekly_signal(weeks["A"].iloc[0])["risk"]["stoploss"] == 930
