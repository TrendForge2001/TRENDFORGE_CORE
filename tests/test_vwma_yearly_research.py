"""Causal annual references, completed daily triggers and reconciled fills."""

import numpy as np
import pandas as pd
import pytest

from backtest.vwma_yearly_engine import VwmaYearlyBacktestEngine
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from scanner.strategy_horizons import horizon_strategy, scanner_horizon_choices
from scanner.strategy_registry import get_strategy
from scanner.vwma_yearly import STRATEGY_ID, add_indicators, entry_plan, evaluate
from services.execution_report import validate_result
from services.portfolio_backtest_service import PortfolioBacktestService
from services.technical_trading_service import TechnicalTradingService

NOW = pd.Timestamp("2026-11-15T17:00:00+05:30")


def history():
    index = pd.bdate_range("2022-01-03", "2026-11-13", tz="Asia/Kolkata")
    x = np.arange(len(index))
    close = 100 + x * 0.04 + 1.5 * np.sin(x / 2) + 2 * np.sin(x / 15)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.3,
            "low": close - 0.5,
            "close": close,
            "volume": np.where(x % 7 == 0, 4000.0, 1000.0),
        },
        index=index,
    )


def execution_frame():
    index = pd.bdate_range("2026-03-02", periods=6, tz="Asia/Kolkata")
    frame = pd.DataFrame(
        {
            "open": [98, 100, 103, 110, 123, 125],
            "high": [99, 102, 104, 120, 129, 126],
            "low": [97, 99, 100, 105, 102, 124],
            "close": [98, 101, 103, 118, 125, 125],
            "volume": 2000.0,
            "VWMA_20": [90, 92, 93, 94, 95, 96],
            "VWMA_50": [85, 86, 87, 88, 89, 90],
            "RSI_WILDER_14": 60.0,
            "VOL_SMA_20": 1100.0,
            "HIGH_20_PREV": 100.0,
            "LOW_5": 95.0,
        },
        index=index,
    )
    for name, value in {
        "P": 70,
        "R1": 80,
        "R2": 90,
        "R3": 100,
        "S1": 60,
        "S2": 50,
        "S3": 40,
    }.items():
        frame["FIB_YEAR_" + name] = float(value)
    return frame.astype(float)


def pivot_frame():
    index = pd.bdate_range("2026-03-02", periods=7, tz="Asia/Kolkata")
    frame = pd.DataFrame(
        {
            "open": [101, 101, 103, 107, 112, 122, 128],
            "high": [103, 104, 107, 113, 125, 132, 130],
            "low": [99, 99, 101, 106, 111, 121, 127],
            "close": [101, 103, 106, 112, 123, 130, 129],
            "volume": 1200.0,
            "VOL_SMA_20": 1000.0,
            "VWMA_20": [99, 101, 102, 103, 104, 105, 106],
            "VWMA_50": [100, 100, 101, 102, 103, 104, 105],
            "RSI_WILDER_14": 60.0,
        },
        index=index,
    )
    for name, value in {
        "P": 100,
        "R1": 110,
        "R2": 120,
        "R3": 130,
        "S1": 90,
        "S2": 80,
        "S3": 70,
    }.items():
        frame["FIB_YEAR_" + name] = float(value)
    return frame.astype(float)


def simulate(frame, **kwargs):
    frames = frame if isinstance(frame, dict) else {"EXAMPLE": frame}
    return VwmaYearlyBacktestEngine().run(
        frames,
        strategy_id=STRATEGY_ID,
        mode="swing",
        interval="1d",
        cost_bps=kwargs.pop("cost_bps", 12),
        slippage_bps=kwargs.pop("slippage_bps", 0),
        **kwargs,
    )


def reconcile(result):
    validate_result(
        {
            "status": "completed",
            **result,
            "parameters": {
                "deployment_limit": 100000.0,
                "cash_reserve": 0.0,
                "max_positions": 3,
            },
        }
    )


def test_fibonacci_formulas_warmup_and_future_invariance():
    raw = history()
    out = add_indicators(raw)
    previous = raw.loc["2025"]
    p = (previous.high.max() + previous.low.min() + previous.close.iloc[-1]) / 3
    span = previous.high.max() - previous.low.min()
    row = out.loc["2026"].iloc[0]
    assert pytest.approx(p) == row.FIB_YEAR_P
    assert pytest.approx(p + 0.382 * span) == row.FIB_YEAR_R1
    assert pytest.approx(p + 0.618 * span) == row.FIB_YEAR_R2
    assert pytest.approx(p + span) == row.FIB_YEAR_R3
    assert pytest.approx(p - span) == row.FIB_YEAR_S3
    assert out.loc["2023", "FIB_YEAR_P"].isna().all()
    prefix = add_indicators(raw.loc[:"2026-04-30"])
    pd.testing.assert_frame_equal(prefix, out.loc[prefix.index])
    missing = add_indicators(raw.loc[raw.index.year != 2025])
    assert missing.loc["2026", "FIB_YEAR_P"].isna().all()


def test_vwma_and_sma20_use_completed_signal_volume():
    raw = history()
    out = add_indicators(raw)
    last20 = raw.iloc[-20:]
    assert (
        pytest.approx((last20.close * last20.volume).sum() / last20.volume.sum())
        == out.iloc[-1].VWMA_20
    )
    assert last20.volume.mean() == out.iloc[-1].VOL_SMA_20


@pytest.mark.parametrize(
    "field,value",
    [
        ("RSI_WILDER_14", 50),
        ("RSI_WILDER_14", 70.01),
        ("volume", 1000),
        ("VWMA_20", 100),
        ("FIB_YEAR_P", np.nan),
        ("low", 100.01),
    ],
)
def test_each_required_entry_confirmation_blocks_entry(field, value):
    frame = pivot_frame()
    current = frame.iloc[1].copy()
    assert evaluate(frame.iloc[0], current)["entry_state"] == "ARMED"
    current[field] = value
    assert evaluate(frame.iloc[0], current)["entry_state"] == "WAIT"


def test_above_65_is_allowed_through_70_but_ranked_below_preferred_range():
    frame = pivot_frame()
    preferred = evaluate(frame.iloc[0], frame.iloc[1])
    row = frame.iloc[1].copy()
    row.RSI_WILDER_14 = 70
    accepted = evaluate(frame.iloc[0], row)
    assert accepted["signal"] == "BUY" and accepted["score"] < preferred["score"]


def test_actual_crossover_required_without_extra_slope_or_high20_filters():
    frame = pivot_frame()
    previous, current = frame.iloc[0].copy(), frame.iloc[1].copy()
    previous.VWMA_20, previous.VWMA_50 = 99, 102
    current.VWMA_20, current.VWMA_50 = 101, 100
    assert evaluate(previous, current)["signal"] == "BUY"  # slow VWMA need not rise
    previous.VWMA_20 = 103
    assert evaluate(previous, current)["entry_state"] == "WAIT"
    previous.name = pd.Timestamp("2025-12-31", tz="Asia/Kolkata")
    current.name = pd.Timestamp("2026-01-02", tz="Asia/Kolkata")
    assert evaluate(previous, current)["entry_state"] == "WAIT"


def test_bearish_setup_is_exit_only_even_without_an_open_position():
    frame = pivot_frame()
    previous, current = frame.iloc[0].copy(), frame.iloc[1].copy()
    previous.VWMA_20, previous.VWMA_50, previous.RSI_WILDER_14 = 101, 100, 55
    current.VWMA_20, current.VWMA_50, current.RSI_WILDER_14 = 99, 100, 49
    current.high, current.close = 112, 109
    result = evaluate(previous, current)
    assert result["signal"] == "EXIT" and result["entry_state"] == "WAIT"
    assert result["direction"] == "LONG" and result["exit_triggered"]
    frame.loc[
        frame.index[1], ["VWMA_20", "VWMA_50", "RSI_WILDER_14", "high", "close"]
    ] = [99, 100, 49, 112, 109]
    frame.loc[frame.index[0], ["VWMA_20", "VWMA_50", "RSI_WILDER_14"]] = [101, 100, 55]
    assert simulate(frame)["trades"] == []


def test_second_support_uses_actual_fill_and_annual_targets():
    row = pivot_frame().iloc[1]
    plan = entry_plan(row, entry=103)
    assert plan["stoploss"] == 90 and plan["partial_target"] == 110
    assert plan["second_target"] == 120 and plan["target2"] == 130
    assert entry_plan(row, entry=99)["stoploss"] == 80
    assert entry_plan(row, entry=110) == {}  # first target already reached
    assert entry_plan(row, entry=75) == {}  # fewer than two lower positive levels
    assert plan["stop_is_resting_order"] is False


def test_next_open_partial_r1_and_final_r3_reconcile():
    frame = pivot_frame()
    result = simulate(frame)
    trade = result["trades"][0]
    assert trade["entry_at"] == frame.index[2].isoformat()
    assert trade["entry_price"] == 103 and trade["initial_stoploss"] == 90
    assert [fill["exit_reason"] for fill in result["exit_fills"]] == [
        "R1_PARTIAL_PROFIT",
        "R3_FINAL_TARGET",
    ]
    assert result["exit_fills"][0]["quantity"] == trade["quantity"] // 2
    assert sum(fill["quantity"] for fill in result["exit_fills"]) == trade["quantity"]
    assert trade["planned_initial_risk"] <= trade["risk_budget"]
    assert [item["reference"] for item in trade["stop_reference_history"]] == [110, 120]
    reconcile(result)


def test_no_price_only_stop_and_no_generic_vwma20_exit():
    frame = pivot_frame()
    frame.loc[frame.index[2], ["low", "close", "volume", "VWMA_20"]] = [
        70,
        85,
        900,
        102,
    ]
    frame.loc[frame.index[3], ["open", "low"]] = [86, 85]
    result = simulate(frame)
    assert result["trades"][0]["exit_reason"] == "R3_FINAL_TARGET"
    assert all("STOP" not in fill["exit_reason"] for fill in result["exit_fills"])
    reconcile(result)


def test_rsi_gap_open_uses_previous_completed_rsi_and_open_price():
    frame = pivot_frame()
    frame.loc[frame.index[2], "RSI_WILDER_14"] = 29
    frame.loc[frame.index[3], ["open", "low"]] = [102, 101]
    result = simulate(frame)
    trade = result["trades"][0]
    assert trade["exit_reason"] == "RSI_GAP_OPEN_EXIT"
    assert trade["exit_at"] == frame.index[3].isoformat() and trade["exit_price"] == 102
    reconcile(result)


def test_current_day_rsi_cannot_retroactively_fill_at_current_open():
    frame = pivot_frame()
    frame.loc[
        frame.index[3], ["open", "high", "low", "close", "RSI_WILDER_14", "volume"]
    ] = [105, 109, 100, 101, 29, 900]
    frame.loc[frame.index[4], ["open", "low"]] = [103, 102]
    result = simulate(frame)
    trade = result["trades"][0]
    assert trade["exit_reason"] == "RSI_GAP_CLOSE_CONFIRMED_EXIT"
    assert trade["exit_at"] == frame.index[4].isoformat() and trade["exit_price"] == 103
    reconcile(result)


def test_selling_volume_support_rule_is_independent_of_rsi_gap_group():
    frame = pivot_frame()
    frame.loc[frame.index[3], ["open", "high", "low", "close", "RSI_WILDER_14"]] = [
        107,
        109,
        84,
        85,
        45,
    ]
    frame.loc[frame.index[4], ["open", "low"]] = [84, 83]
    result = simulate(frame)
    trade = result["trades"][0]
    assert trade["exit_reason"] == "SELLING_VOLUME_SUPPORT_EXIT"
    assert trade["exit_at"] == frame.index[4].isoformat() and trade["exit_price"] == 84
    reconcile(result)


@pytest.mark.parametrize(
    "volume,opening,expected", [(900, 107, False), (1200, 84, False), (1200, 107, True)]
)
def test_support_stop_requires_bearish_volume_confirmation(volume, opening, expected):
    from scanner.vwma_yearly import stop_conditions

    frame = pivot_frame()
    row = frame.iloc[3].copy()
    row.open, row.close, row.volume, row.RSI_WILDER_14 = opening, 85, volume, 45
    assert (
        stop_conditions(frame.iloc[2], row, 90)[
            "selling_volume_and_close_below_support"
        ]
        is expected
    )


def test_r2_rejection_exits_next_open_without_retroactive_target_fill():
    frame = pivot_frame()
    frame.loc[frame.index[4], ["open", "high", "low", "close", "volume"]] = [
        112,
        125,
        111,
        119,
        900,
    ]
    frame.loc[frame.index[5], ["open", "low"]] = [118, 117]
    result = simulate(frame)
    assert [fill["exit_reason"] for fill in result["exit_fills"]] == [
        "R1_PARTIAL_PROFIT",
        "R2_CLOSE_CONFIRMED_PROFIT",
    ]
    assert result["exit_fills"][-1]["exit_at"] == frame.index[5].isoformat()
    assert result["exit_fills"][-1]["exit_price"] == 118
    reconcile(result)


def test_r2_breakout_requires_volume_and_trailing_reference_never_decreases():
    frame = pivot_frame()
    frame.loc[frame.index[4], "volume"] = 900
    assert simulate(frame)["trades"][0]["exit_reason"] == "R2_CLOSE_CONFIRMED_PROFIT"
    result = simulate(pivot_frame())
    refs = [item["reference"] for item in result["trades"][0]["stop_reference_history"]]
    assert refs == sorted(refs) and refs[-1] == 120


def test_trailing_reference_activates_after_close_not_on_that_candles_wick():
    frame = pivot_frame()
    frame.loc[frame.index[3], "low"] = 80
    result = simulate(frame)
    assert result["trades"][0]["exit_reason"] == "R3_FINAL_TARGET"
    reconcile(result)


def test_held_targets_are_frozen_across_annual_reset():
    frame = pivot_frame()
    frame.index = pd.bdate_range("2025-12-29", periods=len(frame), tz="Asia/Kolkata")
    frame.loc[frame.index[3] :, "FIB_YEAR_R3"] = 200
    result = simulate(frame)
    assert result["trades"][0]["target"] == 130
    assert result["trades"][0]["pivot_year"] == 2025


def test_multiple_symbols_share_one_cash_account_and_reference_risk_limit():
    frame = pivot_frame()
    result = simulate(
        {name: frame.copy() for name in ("A", "B", "C", "D")}, slippage_bps=5
    )
    assert (
        len(result["trades"]) == 3 and result["metrics"]["max_observed_positions"] == 3
    )
    assert result["metrics"]["minimum_cash"] >= 0
    assert result["metrics"]["max_capital_committed"] <= 100000
    assert all(
        trade["planned_initial_risk"] <= trade["risk_budget"]
        for trade in result["trades"]
    )
    reconcile(result)


def test_profit_limits_never_fill_below_their_limit_after_slippage():
    result = simulate(pivot_frame(), slippage_bps=50)
    assert result["exit_fills"][0]["exit_price"] >= 110
    assert result["exit_fills"][1]["exit_price"] >= 130
    reconcile(result)


def test_bearish_setup_closes_only_the_held_long_at_next_open():
    frame = pivot_frame()
    frame.loc[
        frame.index[3], ["high", "close", "VWMA_20", "VWMA_50", "RSI_WILDER_14"]
    ] = [112, 109, 99, 100, 49]
    frame.loc[frame.index[4], ["open", "low"]] = [108, 107]
    result = simulate(frame)
    assert result["trades"][0]["exit_reason"] == "BEARISH_SETUP_EXIT"
    assert result["trades"][0]["exit_at"] == frame.index[4].isoformat()
    assert all(trade["side"] == "LONG" for trade in result["trades"])
    reconcile(result)


@pytest.mark.parametrize(
    "volume,reason", [(1200, "SELLING_VOLUME_SUPPORT_EXIT"), (900, "R3_FINAL_TARGET")]
)
def test_raised_trailing_reference_still_requires_combined_stop_conditions(
    volume, reason
):
    frame = pivot_frame()
    frame.loc[
        frame.index[4], ["open", "high", "low", "close", "volume", "RSI_WILDER_14"]
    ] = [115, 116, 107, 108, volume, 45]
    frame.loc[frame.index[5], ["open", "low"]] = [107, 106]
    result = simulate(frame)
    assert result["trades"][0]["exit_reason"] == reason
    assert result["trades"][0]["initial_stoploss"] == 90
    assert result["trades"][0]["stoploss"] == 110
    reconcile(result)


def test_future_prices_cannot_change_prior_fills_or_confirmations():
    frame = pivot_frame()
    result = simulate(frame)
    changed = frame.copy()
    changed.loc[changed.index[-1], ["open", "high", "low", "close", "volume"]] = [
        200,
        250,
        160,
        220,
        50000,
    ]
    assert simulate(changed)["trades"] == result["trades"]


def test_service_scan_backtest_persistence_and_research_catalog(tmp_path, monkeypatch):
    frame = pivot_frame()
    pad_index = pd.bdate_range(
        end=frame.index[0] - pd.Timedelta(days=1), periods=70, tz="Asia/Kolkata"
    )
    pad = pd.DataFrame([frame.iloc[0].to_dict()] * 70, index=pad_index)
    frame = pd.concat([pad, frame])
    monkeypatch.setattr(
        "scanner.vwma_yearly.prepare_daily", lambda *a, **kw: frame.copy()
    )

    class Market:
        calls = []

        def batch_candles_with_errors(self, symbols, **kwargs):
            self.calls.append(kwargs)
            return {symbol: history() for symbol in symbols}, {}

    path = str(tmp_path / "vwma.db")
    initialize_database(path)
    service = TechnicalTradingService(
        market_data=Market(), repository=BacktestResultsRepository(db_path=path)
    )
    try:
        result = PortfolioBacktestService(service).run(
            symbols=["MCX"], mode="swing", strategy_id=STRATEGY_ID, period="2y", now=NOW
        )
        validate_result(result)
        assert result["metrics"]["total_trades"] == 1
        assert result["parameters"]["pivot_type"] == "Fibonacci"
        assert result["parameters"]["stop_is_resting_order"] is False
        assert (
            result["parameters"]["bearish_signal_action"] == "exit_existing_long_only"
        )
        assert result["report"]["xlsx_base64"]
        assert (
            service.repository.by_run_id(result["run_id"])["result"]["report"]
            == result["report"]
        )
        assert service.market_data.calls == [{"period": "5y", "interval": "1d"}]
        scan = service.scan(
            symbols=["MCX"], mode="swing", strategy_id=STRATEGY_ID, period="2y", now=NOW
        )
        assert scan["results"][0]["signal"] != "ERROR"
        assert scan["results"][0]["execution_eligible"] is False
        assert horizon_strategy("short_term", STRATEGY_ID)["interval"] == "1d"
        assert STRATEGY_ID in {
            row["strategy_id"] for row in scanner_horizon_choices("short_term").values()
        }
        assert get_strategy(STRATEGY_ID)["paper_eligible"] is False
        with pytest.raises(ValueError):
            service.scan(
                symbols=["MCX"],
                mode="swing",
                strategy_id=STRATEGY_ID,
                execute_paper=True,
                now=NOW,
            )
    finally:
        service.repository.close()
