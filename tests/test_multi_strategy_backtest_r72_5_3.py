from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from backtest.multi_strategy_backtest_engine import (
    MultiStrategyBacktestEngine,
)
from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
)


def test_r7253_supertrend_strategy_uses_realistic_next_open_bracket():
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 110.0, 101.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 105.0, 100.0],
            "SUPERTREND_DIR": [1.0, 1.0, 1.0, 1.0],
            "RSI_14": [54.0, 60.0, 62.0, 58.0],
            "ATR": [2.0, 2.0, 2.0, 2.0],
        },
        index=index,
    )

    result = MultiStrategyBacktestEngine().run(
        frame,
        strategy_id="tpl_supertrend_rsi",
        mode="swing",
        interval="1d",
        initial_capital=100000.0,
    )

    assert len(result.trades) >= 1
    first = result.trades[0]
    assert first["exit_reason"] == "ATR_TARGET"
    assert first["entry_at"].startswith("2026-01-03")
    assert result.metrics["atr_target_exits"] >= 1
    assert result.metrics["net_profit"] > 0


def test_r7253_positional_mode_is_supported_by_realistic_engine():
    index = pd.date_range("2026-01-01", periods=4, freq="D")
    frame = pd.DataFrame(
        {
            "open": [100.0, 100.0, 100.0, 100.0],
            "high": [101.0, 101.0, 112.0, 101.0],
            "low": [99.0, 99.0, 99.0, 99.0],
            "close": [100.0, 100.0, 106.0, 100.0],
            "MACD": [0.10, 0.30, 0.50, 0.40],
            "MACD_SIGNAL": [0.20, 0.20, 0.30, 0.35],
            "EMA_20": [105.0, 105.0, 105.0, 105.0],
            "EMA_50": [100.0, 100.0, 100.0, 100.0],
            "ATR": [2.0, 2.0, 2.0, 2.0],
        },
        index=index,
    )

    result = MultiStrategyBacktestEngine().run(
        frame,
        strategy_id="tpl_macd_trend_confirmation",
        mode="positional",
        interval="1d",
    )

    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "ATR_TARGET"


def test_intraday_pending_entry_is_cancelled_at_1500_not_carried_overnight():
    tz = ZoneInfo("Asia/Kolkata")
    index = pd.DatetimeIndex(
        [
            datetime(2026, 10, 20, 14, 30, tzinfo=tz),
            datetime(2026, 10, 20, 14, 45, tzinfo=tz),
            datetime(2026, 10, 20, 15, 0, tzinfo=tz),
            datetime(2026, 10, 21, 9, 15, tzinfo=tz),
            datetime(2026, 10, 21, 9, 30, tzinfo=tz),
        ]
    )
    frame = pd.DataFrame(
        {
            "open": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "close": [100.0] * 5,
        },
        index=index,
    )

    def entry(previous, current):
        if current.name.hour == 14 and current.name.minute == 45:
            return {
                "signal": "BUY",
                "entry": 100.0,
                "stoploss": 95.0,
                "target2": 110.0,
                "reward_risk": 2.0,
            }
        return None

    result = TechnicalRealisticBacktestEngine().run(
        frame,
        entry_rule=entry,
        exit_rule=lambda previous, current: None,
        mode="intraday",
    )

    assert result.trades == []
