from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.indicator_engine import IndicatorEngine


def candles(n=60):
    close = np.linspace(100, 160, n)
    return pd.DataFrame({
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": np.full(n, 1000.0),
    })


def test_indicator_engine_requires_30_candles():
    with pytest.raises(ValueError, match="Minimum 30 candles"):
        IndicatorEngine().calculate(candles(29))


def test_indicator_engine_preserves_source_dataframe():
    source = candles()
    original = source.copy(deep=True)
    IndicatorEngine().calculate(source)
    pd.testing.assert_frame_equal(source, original)


def test_indicator_engine_exposes_ema_and_vwma_9_26():
    result = IndicatorEngine().calculate(candles())
    for column in ["EMA_9", "EMA_20", "EMA_50", "EMA_100", "EMA_200", "VWMA_9", "VWMA_26"]:
        assert column in result.columns
        assert np.isfinite(float(result.iloc[-1][column]))


def test_build_snapshot_rejects_non_finite_required_indicator():
    frame = candles()
    engine = IndicatorEngine()
    calculated = engine.calculate(frame)
    calculated.loc[calculated.index[-1], "EMA_50"] = np.nan
    with pytest.raises(ValueError, match="EMA_50 is not finite"):
        engine.build_snapshot("ABC", "1d", calculated)


def test_health_declares_indicator_history_contract():
    health = IndicatorEngine().health()
    assert health["min_candles"] == 30
    assert health["ema"] == [9, 20, 50, 100, 200]
    assert health["vwma"] == [9, 26]
