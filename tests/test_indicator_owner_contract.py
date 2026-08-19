from __future__ import annotations

import numpy as np
import pandas as pd

from engines.market_regime_engine import MarketRegimeEngine
from engines.price_action_engine import PriceActionEngine


class SpyIndicator:
    def __init__(self):
        self.calls = 0

    def calculate(self, frame):
        self.calls += 1
        raise AssertionError("Indicator calculation must be owned by FullScannerPipeline")


def enriched_frame(rows=60):
    close = np.linspace(100, 120, rows)
    frame = pd.DataFrame({
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": np.full(rows, 1000.0),
    })
    numeric = {
        "EMA_20": close - 1, "EMA_50": close - 2, "EMA_200": close - 3,
        "RSI": np.full(rows, 60.0), "MACD": np.full(rows, 1.0),
        "MACD_SIGNAL": np.full(rows, 0.5), "ADX": np.full(rows, 30.0),
        "+DI": np.full(rows, 25.0), "-DI": np.full(rows, 15.0),
        "RVOL": np.full(rows, 1.2), "ATR_PERCENT": np.full(rows, 2.0),
        "BB_WIDTH": np.full(rows, 0.08), "VWMA_9": close - 0.5,
        "VWMA_26": close - 1.0,
        "SUPPORT": close - 5, "RESISTANCE": close + 5,
    }
    for key, value in numeric.items():
        frame[key] = value
    for key in [
        "UPTREND", "DOWNTREND", "BREAKOUT", "BREAKDOWN", "HIGHER_HIGH",
        "HIGHER_LOW", "LOWER_HIGH", "LOWER_LOW", "BULLISH_ENGULFING",
        "BEARISH_ENGULFING", "HAMMER", "DOJI", "INSIDE_BAR", "OUTSIDE_BAR",
        "NR7", "GAP_UP", "GAP_DOWN",
    ]:
        frame[key] = False
    return frame


def test_price_action_engine_does_not_recalculate_indicators():
    spy = SpyIndicator()
    engine = PriceActionEngine(indicator_engine=spy)
    result = engine.evaluate({"df": enriched_frame()})
    assert spy.calls == 0
    assert result.engine == engine.NAME


def test_market_regime_engine_does_not_recalculate_indicators():
    spy = SpyIndicator()
    engine = MarketRegimeEngine(indicator_engine=spy)
    result = engine.evaluate({"df": enriched_frame()})
    assert spy.calls == 0
    assert result.engine == engine.NAME
