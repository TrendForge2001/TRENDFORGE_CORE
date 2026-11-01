"""Owner-rule truth tables, causal reference periods and research-only wiring."""

from datetime import timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from indicators.ema_pivot import add_ema_pivot_indicators
from indicators.indicator_engine import IndicatorEngine
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_registry import get_strategy

IDS = tuple(EMA_PIVOT_SETUPS)


def signal_frame(strategy_id, *, mode="swing"):
    setup = EMA_PIVOT_SETUPS[strategy_id]
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [103.0, 103.0],
            "low": [99.0, 99.0],
            "close": [102.0, 102.0],
            "volume": [200.0, 200.0],
            "EMA_RESEARCH_BARS": [300, 301],
            "RSI_WILDER_14": [
                49.0 if setup.fast == 50 else 58.0,
                51.0 if setup.fast == 50 else 60.0,
            ],
            "MACD": [0.8, 1.0],
            "MACD_SIGNAL": [0.6, 0.6],
            "MACD_HIST": [0.2, 0.4],
            "ATR_WILDER_14": [1.0, 1.0],
            "VOL_SMA_20_PREV": [100.0, 100.0],
            f"EMA_{setup.fast}": [99.0, 101.0],
            f"EMA_{setup.slow}": [100.0, 100.0],
        },
        index=pd.date_range(
            "2026-10-08 10:00" if mode == "intraday" else "2026-10-07",
            periods=2,
            freq="15min" if mode == "intraday" else "B",
            tz="Asia/Kolkata",
        ),
    )
    for period in ("DAY", "WEEK", "MONTH"):
        for level, value in {"P": 90, "R1": 130, "R2": 140, "S1": 80, "S2": 70}.items():
            frame[f"TRAD_{period}_{level}"] = float(value)
    if setup.direction == -1:
        for key in ("open", "close", f"EMA_{setup.fast}", f"EMA_{setup.slow}"):
            frame[key] = 200 - frame[key]
        frame["high"], frame["low"] = 200 - frame["low"], 200 - frame["high"]
        frame["RSI_WILDER_14"] = 100 - frame["RSI_WILDER_14"]
        for key in ("MACD", "MACD_SIGNAL", "MACD_HIST"):
            frame[key] = -frame[key]
        for period in ("DAY", "WEEK", "MONTH"):
            for level, value in {
                "P": 110,
                "R1": 120,
                "R2": 130,
                "S1": 60,
                "S2": 50,
            }.items():
                frame[f"TRAD_{period}_{level}"] = float(value)
    return frame


def evaluate(strategy_id, frame=None, *, mode="swing", **kwargs):
    return MultiStrategyEngine().evaluate(
        signal_frame(strategy_id, mode=mode) if frame is None else frame,
        mode=mode,
        interval="15m" if mode == "intraday" else "1d",
        strategy_ids=[strategy_id],
        **kwargs,
    )["evaluations"][0]


@pytest.mark.parametrize("strategy_id", IDS)
@pytest.mark.parametrize("mode", ["intraday", "swing"])
def test_all_eight_detect_directional_setups_with_the_requested_atr_plan(
    strategy_id, mode
):
    setup = EMA_PIVOT_SETUPS[strategy_id]
    row = evaluate(strategy_id, mode=mode)
    assert row["entry_state"] == "ARMED", row["failed_checks"]
    assert row["signal"] == ("BUY" if setup.direction == 1 else "SELL")
    assert row["score"] == 100
    assert row["paper_eligible"] is True
    plan = row["entry_plan"]
    assert plan["risk_per_share"] == setup.stop_atr
    assert plan["valid_for_next_candle_only"] is True
    assert plan["entry"] == pytest.approx(103.05 if setup.direction == 1 else 96.95)
    assert plan["partial_target"] == pytest.approx(
        plan["entry"] + setup.direction * setup.partial_r * setup.stop_atr
    )
    assert plan["pivot_period"] == (
        "day" if mode == "intraday" else "month" if setup.slow == 200 else "week"
    )
    assert (plan["target2"] is None) == setup.trailing
    assert (
        get_strategy(strategy_id)["implementation_status"] == "staged_paper_execution"
    )


@pytest.mark.parametrize("strategy_id", IDS)
@pytest.mark.parametrize("field", ["ATR_WILDER_14", "RSI_WILDER_14", "MACD", "close"])
def test_nonfinite_required_values_cannot_arm_an_entry(strategy_id, field):
    frame = signal_frame(strategy_id)
    frame.loc[frame.index[-1], field] = np.nan
    assert evaluate(strategy_id, frame)["entry_state"] == "WAIT"


@pytest.mark.parametrize("strategy_id", IDS)
def test_every_required_condition_can_block_a_setup_and_optional_volume_excludes_signal(
    strategy_id,
):
    frame = signal_frame(strategy_id)
    frame.loc[frame.index[-1], "volume"] = 150
    assert evaluate(strategy_id, frame)["entry_state"] == "ARMED"
    assert (
        evaluate(strategy_id, frame, liquidity_confirmation=True)["entry_state"]
        == "WAIT"
    )
    frame.loc[frame.index[-1], "volume"] = 150.01
    assert (
        evaluate(strategy_id, frame, liquidity_confirmation=True)["entry_state"]
        == "ARMED"
    )
    setup = EMA_PIVOT_SETUPS[strategy_id]
    frame.loc[frame.index[-1], "EMA_RESEARCH_BARS"] = setup.slow
    assert evaluate(strategy_id, frame)["entry_state"] == "WAIT"
    frame.loc[frame.index[-1], "EMA_RESEARCH_BARS"] = 301
    frame.loc[frame.index[-1], f"TRAD_{setup.pivot_period('swing')}_P"] = np.nan
    assert evaluate(strategy_id, frame)["entry_state"] == "WAIT"


@pytest.mark.parametrize("strategy_id", IDS)
def test_stale_crosses_and_wrong_histogram_slope_are_not_new_signals(strategy_id):
    frame = signal_frame(strategy_id)
    setup = EMA_PIVOT_SETUPS[strategy_id]
    if setup.fast == 50:
        frame.loc[frame.index[0], "RSI_WILDER_14"] = frame.iloc[-1]["RSI_WILDER_14"]
    else:
        frame.loc[frame.index[0], f"EMA_{setup.fast}"] = frame.iloc[-1][
            f"EMA_{setup.fast}"
        ]
    assert evaluate(strategy_id, frame)["entry_state"] == "WAIT"
    if setup.fast in (9, 50):
        frame = signal_frame(strategy_id)
        frame.loc[frame.index[-1], "MACD_HIST"] = frame.iloc[0]["MACD_HIST"]
        assert evaluate(strategy_id, frame)["entry_state"] == "WAIT"


def test_pivot_headroom_rejects_less_than_1_5r_and_explains_absent_resistance():
    key = IDS[0]
    frame = signal_frame(key)
    frame["TRAD_WEEK_R1"] = 104
    row = evaluate(key, frame)
    assert row["entry_state"] == "WAIT"
    assert "pivot_room_at_least_1_5r" in row["failed_checks"]
    frame["TRAD_WEEK_R1"] = frame["TRAD_WEEK_R2"] = 95
    row = evaluate(key, frame)
    assert row["entry_state"] == "ARMED"
    assert row["entry_plan"]["pivot_room_r"] is None
    assert "No further level" in row["entry_plan"]["pivot_room_note"]


@pytest.mark.parametrize("strategy_id", IDS)
def test_opening_candle_can_cross_against_previous_session_indicators(strategy_id):
    frame = signal_frame(strategy_id, mode="intraday")
    frame.index = pd.DatetimeIndex(
        ["2026-10-07 15:15", "2026-10-08 09:15"], tz="Asia/Kolkata"
    )
    assert evaluate(strategy_id, frame, mode="intraday")["entry_state"] == "ARMED"


def test_wilder_seed_prior_volume_and_period_pivots_are_prefix_invariant():
    index = pd.bdate_range("2026-01-01", periods=220, tz="Asia/Kolkata")
    prices = 100 + np.sin(np.arange(220) / 5) * 4 + np.arange(220) / 10
    raw = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 2,
            "low": prices - 2,
            "close": prices,
            "volume": np.arange(220) + 100,
        },
        index=index,
    )
    full = add_ema_pivot_indicators(raw.copy())
    for size in (22, 47, 100, 200):
        prefix = add_ema_pivot_indicators(raw.iloc[:size].copy())
        pd.testing.assert_frame_equal(full.loc[prefix.index, prefix.columns], prefix)
    assert full["VOL_SMA_20_PREV"].iloc[20] == raw["volume"].iloc[:20].mean()
    assert full["ATR_WILDER_14"].iloc[13] == 4
    delta = raw["close"].diff().iloc[1:15]
    expected_rsi = 100 - 100 / (
        1 + delta.clip(lower=0).mean() / (-delta.clip(upper=0)).mean()
    )
    assert full["RSI_WILDER_14"].iloc[14] == pytest.approx(expected_rsi)
    stamp = pd.Timestamp("2026-04-08", tz="Asia/Kolkata")
    previous_week = raw.loc["2026-03-30":"2026-04-03"]
    h, low, close = (
        previous_week["high"].max(),
        previous_week["low"].min(),
        previous_week["close"].iloc[-1],
    )
    p = (h + low + close) / 3
    assert full.loc[stamp, "TRAD_WEEK_P"] == pytest.approx(p)
    assert full.loc[stamp, "TRAD_WEEK_R1"] == pytest.approx(2 * p - low)
    assert full.loc[stamp, "TRAD_WEEK_R2"] == pytest.approx(p + h - low)
    previous_month = raw.loc["2026-03"]
    expected = (
        previous_month["high"].max()
        + previous_month["low"].min()
        + previous_month["close"].iloc[-1]
    ) / 3
    assert full.loc[stamp, "TRAD_MONTH_P"] == pytest.approx(expected)
    calculated = IndicatorEngine().calculate(raw)
    assert "EMA_26" in calculated
    assert calculated["EMA_26"].iloc[-1] == pytest.approx(
        raw["close"].ewm(span=26, adjust=False).mean().iloc[-1]
    )


def test_intraday_daily_pivots_use_only_the_previous_complete_nse_session():
    dates = pd.bdate_range("2026-10-05", periods=3, tz="Asia/Kolkata")
    index = pd.DatetimeIndex(
        [stamp + timedelta(minutes=555 + 15 * n) for stamp in dates for n in range(25)]
    )
    prices = np.repeat([100.0, 110.0, 120.0], 25)
    frame = pd.DataFrame(
        {
            "open": prices,
            "high": prices + 2,
            "low": prices - 2,
            "close": prices,
            "volume": 100,
        },
        index=index,
    )
    calculated = add_ema_pivot_indicators(frame.copy())
    assert calculated["TRAD_DAY_P"].iloc[-1] == 110
    assert calculated["TRAD_DAY_P"].iloc[:50].isna().all()
    truncated = frame.drop(frame.index[30])
    assert add_ema_pivot_indicators(truncated)["TRAD_DAY_P"].iloc[-1:].isna().all()
    utc = frame.copy()
    utc.index = utc.index.tz_convert("UTC")
    pd.testing.assert_series_equal(
        add_ema_pivot_indicators(utc)["TRAD_DAY_P"].tz_convert("Asia/Kolkata"),
        calculated["TRAD_DAY_P"],
    )


def test_staged_setups_are_included_in_full_paper_validation():
    from services.multi_strategy_validation_service import (
        MultiStrategyValidationService,
    )

    service = MultiStrategyValidationService.__new__(MultiStrategyValidationService)
    service.strategy_engine = MultiStrategyEngine()
    service.backtester = SimpleNamespace(
        readiness=lambda: {"backtestable_strategy_ids": list(IDS)}
    )
    included, excluded = service._mode_strategies(
        mode="swing", source="all", strategy_ids=list(IDS)
    )
    assert len(included) == 8 and excluded == []
    assert all(row["paper_eligible"] for row in included)
