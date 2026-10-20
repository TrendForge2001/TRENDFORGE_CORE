from __future__ import annotations

import math

import numpy as np
import pandas as pd

from indicators.indicator_engine import IndicatorEngine


def _frame(rows: int = 320) -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=rows, freq="D")
    x = np.arange(rows, dtype=float)
    close = 100.0 + x * 0.08 + np.sin(x / 4.0) * 3.0
    open_ = close + np.cos(x / 7.0) * 0.4
    high = np.maximum(open_, close) + 1.2
    low = np.minimum(open_, close) - 1.1
    volume = 1_000_000.0 + (x % 17) * 30_000.0
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=index,
    )


def test_r7251_indicator_completion_outputs_are_present_and_usable():
    output = IndicatorEngine().calculate(_frame())
    required = {
        "VWMA_50",
        "VWMA_100",
        "RSI_14",
        "RSI_20",
        "RSI_SMOOTH_14",
        "VOL_SMA_20",
        "VOL_SMA_50",
        "SUPERTREND_10_3",
        "SUPERTREND_DIR",
        "FIB_PIVOT",
        "FIB_R1",
        "FIB_R2",
        "FIB_R3",
        "FIB_S1",
        "FIB_S2",
        "FIB_S3",
        "HIGH_252",
        "LOW_252",
        "DIST_52W_HIGH_PCT",
    }
    assert required.issubset(output.columns)

    row = output.iloc[-1]
    for key in required - {"SUPERTREND_DIR"}:
        assert math.isfinite(float(row[key])), key
    assert int(row["SUPERTREND_DIR"]) in {-1, 1}


def test_indicator_health_describes_completed_registry_dependencies():
    health = IndicatorEngine().health()
    assert health["version"] == "R72.5.1"
    assert health["vwma"] == [9, 26, 50, 100]
    assert health["rsi"] == [14, 20]
    assert health["volume_ma"] == [20, 50]
    assert health["supertrend"] == {"length": 10, "multiplier": 3.0}
    assert health["fibonacci_pivots"] is True
    assert health["rolling_52week_context"] is True
