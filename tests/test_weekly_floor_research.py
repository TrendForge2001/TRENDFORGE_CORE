"""Causal weekly signals, fixed annual targets and reconciled simulated fills."""

import base64
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from backtest.weekly_floor_engine import simulate_weekly
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_horizons import horizon_strategy
from scanner.strategy_registry import get_strategy
from scanner.weekly_floor import (
    STRATEGY_ID,
    daily_history,
    weekly_indicators,
    weekly_signal,
    yearly_pivots,
)
from services.execution_report import validate_result
from services.portfolio_backtest_service import PortfolioBacktestService
from services.research_batches import ResearchBatchManager
from services.research_capacity import research_partitions
from services.technical_trading_service import TechnicalTradingService
from tests.support.weekly_floor_candles import NOW, ExampleMarket, example_history
from tests.test_research_batches import finish, request


@pytest.fixture
def technical(tmp_path):
    path = str(tmp_path / "weekly.db")
    initialize_database(path)
    value = TechnicalTradingService(
        market_data=ExampleMarket(), repository=BacktestResultsRepository(db_path=path)
    )
    yield value
    value.repository.close()


def prepared():
    daily = daily_history(example_history(), now=NOW)
    weekly, annual = weekly_indicators(daily, now=NOW)
    return daily, weekly, annual


def test_floor_pivots_use_only_previous_completed_year():
    daily, _, annual = prepared()
    previous = daily.loc["2025"]
    high, low, close = previous.high.max(), previous.low.min(), previous.close.iloc[-1]
    pivot = (high + low + close) / 3
    assert annual[2026]["FLOOR_YEAR_P"] == pytest.approx(pivot)
    assert annual[2026]["FLOOR_YEAR_R2"] == pytest.approx(pivot + high - low)
    changed = daily.copy()
    changed.loc["2026", "high"] *= 10
    assert yearly_pivots(changed)[2026] == annual[2026]
    assert 2022 not in annual  # Initial observed 2021 is truncated.


def test_volume_ema30_and_body_midpoint_match_owner_conditions():
    _, weekly, _ = prepared()
    row = weekly.loc["2026-03-29"].iloc[0]
    previous = weekly.loc[: row.name].iloc[-2]
    assert (previous.open + previous.close) / 2 == row.PREVIOUS_BODY_MIDPOINT
    assert row.open < previous.close
    result = weekly_signal(row)
    assert result["signal"] == "BUY"
    assert all(result["checks"].values())
    assert row.volume > row.VOL_EMA_30
    assert result["risk"]["stoploss"] < row.low


@pytest.mark.parametrize(
    "field,value", [("open", 200), ("volume", 0), ("RSI_WILDER_14", 50), ("MACD", -100)]
)
def test_failed_confirmation_does_not_buy(field, value):
    _, weekly, _ = prepared()
    row = weekly.loc["2026-03-29"].iloc[0].copy()
    row[field] = value
    assert weekly_signal(row)["signal"] == "HOLD"


def test_incomplete_week_is_not_visible_and_future_data_cannot_change_past_signals():
    daily, weekly, _ = prepared()
    saturday = pd.Timestamp("2026-03-28T12:00:00+05:30")
    prefix, _ = weekly_indicators(daily.loc[:"2026-03-27"], now=saturday)
    assert prefix.index[-1] < pd.Timestamp("2026-03-23", tz="Asia/Kolkata")
    cutoff = pd.Timestamp("2026-03-30T08:00:00+05:30")
    prefix, _ = weekly_indicators(daily.loc[:"2026-03-27"], now=cutoff)
    pd.testing.assert_frame_equal(prefix, weekly.loc[prefix.index], check_freq=False)


def test_special_sunday_session_belongs_to_previous_monday_week():
    daily, _, _ = prepared()
    extra = daily.loc[[pd.Timestamp("2026-03-27T09:15:00+05:30")]].copy()
    extra.index = pd.DatetimeIndex(["2026-03-29T09:15:00+05:30"])
    extra["volume"] = 20000
    combined = pd.concat([daily, extra]).sort_index()
    weeks, _ = weekly_indicators(combined, now=NOW)
    assert weeks.loc["2026-03-29"].iloc[0].volume == 35000


def test_general_test_trades_include_target_stop_and_final_mark_with_costs(technical):
    result = PortfolioBacktestService(technical).run(
        symbols=["EXAMPLE"],
        mode="positional",
        strategy_id=STRATEGY_ID,
        period="2y",
        now=NOW,
    )
    validate_result(result)
    assert {"YEARLY_R2", "PROTECTIVE_STOP", "END_OF_TEST"} <= {
        t["exit_reason"] for t in result["trades"]
    }
    assert all(
        pd.Timestamp(t["entry_at"]) > pd.Timestamp(t["entry_signal_at"])
        for t in result["trades"]
    )
    assert all(t["transaction_costs"] > 0 for t in result["trades"])
    assert result["parameters"]["partial_exits"] is False
    assert technical.market_data.calls == [{"interval": "1d", "period": "5y"}]
    assert result["period"] == "2y"
    saved = technical.repository.by_run_id(result["run_id"])
    assert saved["result"]["report"] == result["report"]
    book = load_workbook(
        BytesIO(base64.b64decode(result["report"]["xlsx_base64"])), read_only=True
    )
    assert "Trade entries and exits" in book.sheetnames
    book.close()


def test_same_daily_bar_stop_has_priority_and_levels_are_not_recentered():
    daily, weekly, annual = prepared()
    daily.loc["2026-03-31", "low"] = 70
    result = simulate_weekly(
        {"EXAMPLE": daily}, {"EXAMPLE": weekly}, {"EXAMPLE": annual}
    )
    first = result["trades"][0]
    assert first["exit_reason"] == "PROTECTIVE_STOP"
    signal = weekly_signal(weekly.loc["2026-03-29"].iloc[0])
    assert first["stoploss"] == signal["risk"]["stoploss"]
    assert first["target2"] == annual[2026]["FLOOR_YEAR_R2"]


def test_opening_gap_beyond_target_skips_entry():
    daily, weekly, annual = prepared()
    daily.loc["2026-03-30", ["open", "high", "low", "close"]] = [250, 251, 249, 250]
    result = simulate_weekly(
        {"EXAMPLE": daily}, {"EXAMPLE": weekly}, {"EXAMPLE": annual}
    )
    assert any(
        r["reason"] == "opening_gap_invalidates_fixed_stop_or_R2"
        for r in result["rejected_entries"]
    )
    assert not any(t["entry_at"].startswith("2026-03-30") for t in result["trades"])


def test_registry_routes_weekly_research_without_enabling_paper_or_daily_scans():
    definition = get_strategy(STRATEGY_ID)
    assert definition["paper_eligible"] is False
    assert horizon_strategy("long_term", STRATEGY_ID)["interval"] == "1wk"
    assert STRATEGY_ID not in {
        r["strategy_id"] for r in MultiStrategyEngine().strategies(mode="positional")
    }


def test_cloud_partition_budget_includes_five_year_warmup(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    settings = horizon_strategy("long_term", STRATEGY_ID, "2y")
    parts = research_partitions(
        ["S" + str(i) for i in range(100)], settings, [settings]
    )
    assert max(len(p["symbols"]) for p in parts) <= 33
    assert sum(len(p["symbols"]) for p in parts) == 100


def test_batch_backtest_uses_weekly_pipeline_and_generates_report(technical):
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        batch = finish(
            manager,
            manager.submit(
                "backtest",
                request(
                    symbols=["EXAMPLE"],
                    horizon="long_term",
                    strategy_id=STRATEGY_ID,
                    period="5y",
                ),
            ),
        )
        assert batch["status"] == "completed"
        assert batch["report"]["parameters"]["signal_interval"] == "1wk"
        assert batch["report"]["parameters"]["broker_orders_allowed"] is False
    finally:
        manager.close(wait=True)


def test_scanner_rejects_paper_execution_and_insufficient_weekly_history(technical):
    with pytest.raises(ValueError, match="research only"):
        technical.scan(
            symbols=["EXAMPLE"],
            mode="positional",
            strategy_id=STRATEGY_ID,
            execute_paper=True,
            now=NOW,
        )
    technical.market_data.frame = example_history().iloc[-200:]
    scan = technical.scan(
        symbols=["EXAMPLE"], mode="positional", strategy_id=STRATEGY_ID, now=NOW
    )
    assert scan["results"][0]["signal"] == "ERROR"
    assert scan["error_symbols"] == 1


def test_macd_confirmation_can_be_below_zero_and_sell_is_long_exit_only():
    _, weekly, _ = prepared()
    row = weekly.loc["2026-03-29"].iloc[0].copy()
    row["MACD"], row["MACD_SIGNAL"] = -0.5, -1.0
    assert weekly_signal(row)["signal"] == "BUY"
    row["close"] = row.FLOOR_YEAR_R2
    result = weekly_signal(row)
    assert result["signal"] == "SELL"
    assert "exits an existing long" in result["signal_semantics"]


def test_friday_holiday_still_enters_only_after_completed_week():
    daily, _, _ = prepared()
    fields = ["close", "high", "volume"]
    daily.loc["2026-03-26", fields] = daily.loc["2026-03-27", fields].to_numpy()
    daily = daily.loc[daily.index.date != pd.Timestamp("2026-03-27").date()]
    weekly, annual = weekly_indicators(daily, now=NOW)
    result = simulate_weekly(
        {"EXAMPLE": daily}, {"EXAMPLE": weekly}, {"EXAMPLE": annual}
    )
    assert result["trades"][0]["entry_at"].startswith("2026-03-30")


def test_weekly_hold_is_preserved_in_saved_scanner_report(technical):
    from services.research_report import build_report

    result = technical.scan(
        symbols=["EXAMPLE"], mode="positional", strategy_id=STRATEGY_ID, now=NOW
    )
    assert result["results"][0]["signal"] == "HOLD"
    report = build_report(
        result, kind="scan", horizon="long_term", stock_list="NIFTY 50"
    )
    assert report["rows"][0]["signal"] == "HOLD"
    assert "existing long" in report["rows"][0]["signal_semantics"]


def test_long_term_dropdown_submits_new_weekly_strategy(monkeypatch):
    from tests.test_r726_ui_runtime_regressions import Client, button, page

    client = Client()
    app = page(monkeypatch, "technical_scanner.py", client)
    app.session_state["scanner_horizon"] = "Long Term"
    app.run(timeout=15)
    widget = next(w for w in app.selectbox if w.label == "Long Term strategy")
    widget.select(get_strategy(STRATEGY_ID)["name"]).run(timeout=15)
    button(app, "Scan stocks").click().run(timeout=15)
    assert not app.exception
    assert client.calls[-1][1]["strategy_id"] == STRATEGY_ID
    assert client.calls[-1][1]["horizon"] == "long_term"


def test_entry_year_target_remains_fixed_across_new_year():
    daily, _, _ = prepared()
    extra = pd.DataFrame(
        {"open": 123.0, "high": 124.0, "low": 122.0, "close": 123.0, "volume": 1000.0},
        index=pd.bdate_range("2026-11-09", "2027-01-05", tz="Asia/Kolkata"),
    )
    raw = pd.concat([daily.tz_convert("Asia/Kolkata"), extra])
    combined = daily_history(raw, now=pd.Timestamp("2027-01-06T08:00:00+05:30"))
    combined.loc["2027-01-04", "high"] = 230
    weekly, annual = weekly_indicators(
        combined, now=pd.Timestamp("2027-01-06T08:00:00+05:30")
    )
    result = simulate_weekly(
        {"EXAMPLE": combined.loc["2026-10":]}, {"EXAMPLE": weekly}, {"EXAMPLE": annual}
    )
    trade = result["trades"][0]
    assert trade["exit_at"].startswith("2027-01-04")
    assert trade["target2"] == annual[2026]["FLOOR_YEAR_R2"]
    assert trade["target2"] != annual[2027]["FLOOR_YEAR_R2"]
