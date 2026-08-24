"""Contract tests for the canonical indicator pipeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from indicators.indicator_engine import IndicatorEngine


def sample_ohlcv(rows: int = 120) -> pd.DataFrame:
    x = np.arange(rows, dtype=float)
    close = 100 + (x * 0.12) + np.sin(x / 5.0) * 2
    return pd.DataFrame({
        "open": close - 0.4,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": 100000 + (x * 250),
    })


def test_indicator_engine_produces_required_contract():
    result = IndicatorEngine().calculate(sample_ohlcv())
    missing = set(IndicatorEngine.REQUIRED_OUTPUTS) - set(result.columns)
    assert not missing
    assert len(result) == 120


def test_indicator_engine_rejects_short_history():
    with pytest.raises(ValueError, match="Minimum 30 candles"):
        IndicatorEngine().calculate(sample_ohlcv(29))


def test_indicator_engine_rejects_missing_ohlcv_column():
    frame = sample_ohlcv().drop(columns=["volume"])
    with pytest.raises(ValueError, match="Missing columns"):
        IndicatorEngine().calculate(frame)
