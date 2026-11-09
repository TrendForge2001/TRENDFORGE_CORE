"""Validation acceleration must preserve complete historical accounting."""

import pandas as pd
import pytest

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from indicators.indicator_engine import IndicatorEngine
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import (
    CONFIRMATION_ONLY,
    REVIEW_REQUIRED,
    MultiStrategyEngine,
)
from scanner.strategy_registry import list_strategies
from tests.support.research_candles import SyntheticMarket


class PublicFrameEngine(MultiStrategyEngine):
    """Keep the original public two-row DataFrame evaluation as the reference."""

    def __init__(self):
        self.calls = 0

    def evaluate(self, *args, **kwargs):
        self.calls += 1
        return super().evaluate(*args, **kwargs)


@pytest.fixture(scope="module")
def frames():
    output = {}
    for interval in ("15m", "1d"):
        raw = SyntheticMarket().batch_candles_with_errors(
            ["SYNTHETIC"], interval=interval
        )[0]["SYNTHETIC"]
        output[interval] = IndicatorEngine().calculate(raw)
    return output


CASES = [
    (row["strategy_id"], mode, "15m" if mode == "intraday" else "1d")
    for row in list_strategies()
    if row["strategy_id"]
    not in set(EMA_PIVOT_SETUPS) | REVIEW_REQUIRED | CONFIRMATION_ONLY
    for mode in row["modes"]
]


@pytest.mark.parametrize("strategy_id,mode,interval", CASES)
def test_direct_evaluation_preserves_every_trade_equity_point_and_metric(
    frames, strategy_id, mode, interval
):
    frame = frames[interval]
    original = frame.copy(deep=True)
    settings = {
        "strategy_id": strategy_id,
        "mode": mode,
        "interval": interval,
        "initial_capital": 100_000,
        "cost_bps": 4 if mode == "intraday" else 12,
        "slippage_bps": 5,
    }
    reference_engine = PublicFrameEngine()
    reference = MultiStrategyBacktestEngine(strategy_engine=reference_engine).run(
        frame, **settings
    )
    accelerated = MultiStrategyBacktestEngine().run(frame, **settings)
    assert reference_engine.calls > 0
    assert accelerated.trades == reference.trades
    assert accelerated.equity_curve == reference.equity_curve
    assert accelerated.metrics == reference.metrics
    pd.testing.assert_frame_equal(frame, original)
