from __future__ import annotations

import pandas as pd

from engines.canonical_market_regime_engine import CanonicalMarketRegimeEngine
from engines.canonical_price_action_engine import CanonicalPriceActionEngine


def _frame(rows: int = 60) -> pd.DataFrame:
    data = {
        "open": [100.0] * rows,
        "high": [102.0] * rows,
        "low": [98.0] * rows,
        "close": [101.0] * rows,
        "volume": [1000.0] * rows,
        "EMA_20": [100.0] * rows,
        "EMA_50": [99.0] * rows,
        "EMA_200": [98.0] * rows,
        "RSI": [60.0] * rows,
        "MACD": [1.0] * rows,
        "MACD_SIGNAL": [0.5] * rows,
        "ADX": [30.0] * rows,
        "RVOL": [1.5] * rows,
        "ATR_PERCENT": [2.0] * rows,
        "BB_WIDTH": [0.10] * rows,
        "SUPPORT": [95.0] * rows,
        "RESISTANCE": [105.0] * rows,
        "UPTREND": [True] * rows,
        "DOWNTREND": [False] * rows,
        "BREAKOUT": [False] * rows,
        "BREAKDOWN": [False] * rows,
    }
    return pd.DataFrame(data)


def test_price_action_facade_does_not_recalculate():
    engine = CanonicalPriceActionEngine()
    frame = _frame()
    calls = []

    def forbidden_calculate(df):
        calls.append(True)
        raise AssertionError("canonical price-action facade must not calculate indicators")

    engine.indicators.calculate = forbidden_calculate
    result = engine.evaluate({"df": frame})

    assert calls == []
    assert result.engine == "Price Action Engine"


def test_market_regime_facade_does_not_recalculate():
    engine = CanonicalMarketRegimeEngine()
    frame = _frame()
    calls = []

    def forbidden_calculate(df):
        calls.append(True)
        raise AssertionError("canonical market-regime facade must not calculate indicators")

    engine.indicators.calculate = forbidden_calculate
    result = engine.evaluate({"df": frame})

    assert calls == []
    assert result.engine == "Market Regime Engine"


def test_canonical_facades_are_pass_through_indicator_owners():
    frame = _frame()
    for engine in (CanonicalPriceActionEngine(), CanonicalMarketRegimeEngine()):
        calculated = engine.indicators.calculate(frame)
        assert calculated is frame
