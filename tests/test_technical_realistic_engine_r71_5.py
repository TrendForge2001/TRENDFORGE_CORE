from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
    TechnicalRealisticConfig,
)


def _daily_frame(*, both=False):
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 102.0, 111.0, 101.0],
            "low": [99.0, 99.0, 94.0 if both else 99.0, 99.0],
            "close": [100.0, 100.0, 105.0, 100.0],
        },
        index=index,
    )


def _entry(previous, current):
    if current.name == pd.Timestamp("2026-01-02"):
        return {
            "signal": "BUY",
            "entry": 100.0,
            "stoploss": 95.0,
            "target2": 110.0,
            "reward_risk": 2.0,
        }
    return None


def _no_exit(previous, current):
    return None


def test_r715_target_executes_from_ohlc_after_next_open_entry():
    result = TechnicalRealisticBacktestEngine(
        TechnicalRealisticConfig(initial_capital=100000.0)
    ).run(
        _daily_frame(both=False),
        entry_rule=_entry,
        exit_rule=_no_exit,
        mode="swing",
    )
    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "ATR_TARGET"
    assert result.trades[0]["exit_price"] == 110.0
    assert result.metrics["atr_target_exits"] == 1


def test_r715_same_bar_stop_first_is_conservative():
    result = TechnicalRealisticBacktestEngine(
        TechnicalRealisticConfig(
            initial_capital=100000.0,
            same_bar_priority="stop",
        )
    ).run(
        _daily_frame(both=True),
        entry_rule=_entry,
        exit_rule=_no_exit,
        mode="swing",
    )
    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "ATR_STOP"
    assert result.trades[0]["exit_price"] == 95.0
    assert result.metrics["atr_stop_exits"] == 1


def test_r715_intraday_position_is_flat_at_1500_ist():
    tz = ZoneInfo("Asia/Kolkata")
    index = pd.DatetimeIndex(
        [
            datetime(2026, 10, 20, 14, 0, tzinfo=tz),
            datetime(2026, 10, 20, 14, 15, tzinfo=tz),
            datetime(2026, 10, 20, 14, 30, tzinfo=tz),
            datetime(2026, 10, 20, 14, 45, tzinfo=tz),
            datetime(2026, 10, 20, 15, 0, tzinfo=tz),
        ]
    )
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0, 102.0],
            "high": [101.0, 101.0, 101.0, 102.0, 103.0],
            "low": [99.0, 99.0, 99.0, 99.0, 101.0],
            "close": [100.0, 100.0, 100.0, 101.0, 102.0],
        },
        index=index,
    )

    def entry(previous, current):
        if current.name.hour == 14 and current.name.minute == 15:
            return {
                "signal": "BUY",
                "entry": 100.0,
                "stoploss": 90.0,
                "target2": 120.0,
                "reward_risk": 2.0,
            }
        return None

    result = TechnicalRealisticBacktestEngine().run(
        frame,
        entry_rule=entry,
        exit_rule=_no_exit,
        mode="intraday",
    )
    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "INTRADAY_SESSION_EXIT_1500"
    assert "15:00:00" in result.trades[0]["exit_at"]
    assert result.metrics["session_exits"] == 1


def test_r715_costs_and_slippage_reduce_result():
    free = TechnicalRealisticBacktestEngine(
        TechnicalRealisticConfig(initial_capital=100000.0)
    ).run(
        _daily_frame(both=False),
        entry_rule=_entry,
        exit_rule=_no_exit,
        mode="swing",
    )
    friction = TechnicalRealisticBacktestEngine(
        TechnicalRealisticConfig(
            initial_capital=100000.0,
            cost_bps=12.0,
            slippage_bps=5.0,
        )
    ).run(
        _daily_frame(both=False),
        entry_rule=_entry,
        exit_rule=_no_exit,
        mode="swing",
    )
    assert friction.metrics["net_profit"] < free.metrics["net_profit"]
    assert friction.metrics["transaction_costs"] > 0
    assert friction.metrics["slippage_impact_estimate"] > 0
