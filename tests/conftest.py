from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [99.0, 100.0, 101.0, 102.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [98.0, 99.0, 100.0, 101.0],
            "close": [100.0, 101.0, 102.0, 103.0],
            "volume": [1000, 1200, 1100, 1400],
        },
        index=pd.date_range("2026-01-01", periods=4, freq="D"),
    )


@pytest.fixture
def multiindex_ohlcv_frame(ohlcv_frame: pd.DataFrame) -> pd.DataFrame:
    frame = ohlcv_frame.copy()
    frame.columns = pd.MultiIndex.from_tuples((column, "ABC") for column in frame.columns)
    return frame


@pytest.fixture
def empty_ohlcv_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
