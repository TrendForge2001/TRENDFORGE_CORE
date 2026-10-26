from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from backtest.multi_strategy_backtest_engine import (
    MultiStrategyBacktestEngine,
)
from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
)


@pytest.mark.parametrize("strategy_id,mode", [
    ("tpl_supertrend_rsi", "swing"), ("tpl_macd_trend_confirmation", "positional"),
    ("tf_medium_ema50_100", "positional"), ("tf_long_ema100_200", "positional"),
])
def test_retired_or_unreviewed_strategy_cannot_be_backtested(strategy_id, mode):
    with pytest.raises((ValueError, KeyError)):
        MultiStrategyBacktestEngine().validate_strategy(strategy_id, mode=mode)


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
