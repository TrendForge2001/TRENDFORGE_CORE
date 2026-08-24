"""Contract tests for the canonical technical/price-action/risk engine layer."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.price_action_engine import PriceActionEngine
from engines.risk_engine import RiskEngine
from engines.technical_engine import TechnicalEngine


def sample_ohlcv(rows: int = 80) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100 + np.cumsum(rng.normal(0.25, 1.0, rows))
    high = close + rng.uniform(0.2, 1.5, rows)
    low = close - rng.uniform(0.2, 1.5, rows)
    open_ = close + rng.normal(0, 0.4, rows)
    volume = rng.integers(100_000, 500_000, rows)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
    })


def test_technical_engine_contract():
    result = TechnicalEngine().evaluate({"symbol": "TEST", "df": sample_ohlcv()})
    assert result.engine == "Technical Engine"
    assert 0 <= result.score <= 100
    assert 0 <= result.confidence <= 100
    assert result.grade in {"A+", "A", "B", "C", "D"}


def test_price_action_engine_contract():
    result = PriceActionEngine().evaluate({"symbol": "TEST", "df": sample_ohlcv()})
    assert result.engine == "Price Action Engine"
    assert 0 <= result.score <= 100
    assert 0 <= result.confidence <= 100


def test_risk_engine_requires_positive_atr_and_price():
    result = RiskEngine().evaluate({"symbol": "TEST", "snapshot": {"close": 100, "atr": 2}, "capital": 100000})
    assert result.engine == "Risk Engine"
    assert result.metrics["entry"] == 100
    assert result.metrics["stoploss"] < 100
    assert result.metrics["target2"] > result.metrics["target1"]


def test_risk_engine_rejects_missing_atr():
    result = RiskEngine().evaluate({"symbol": "TEST", "snapshot": {"close": 100}, "capital": 100000})
    assert result.passed is False
    assert "ATR" in " ".join(result.warnings)
