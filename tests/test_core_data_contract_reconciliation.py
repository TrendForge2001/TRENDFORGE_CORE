from __future__ import annotations

import pandas as pd

from core.data_contract import MarketDataContract
from core.integration_health import IntegrationHealth


def valid_frame():
    return pd.DataFrame({
        "open": [99.0, 100.0],
        "high": [101.0, 102.0],
        "low": [98.0, 99.0],
        "close": [100.0, 101.0],
        "volume": [1000, 1200],
    })


def test_market_data_contract_accepts_canonical_ohlcv():
    result = MarketDataContract.validate(valid_frame())
    assert result.valid is True
    assert result.rows == 2
    assert result.missing == ()


def test_market_data_contract_rejects_bad_price_geometry():
    frame = valid_frame()
    frame.loc[0, "high"] = 90
    result = MarketDataContract.validate(frame)
    assert result.valid is False
    assert "high_below_low_detected" in result.reasons


def test_market_data_contract_rejects_non_numeric_ohlcv():
    frame = valid_frame()
    frame["close"] = ["100", "101"]
    result = MarketDataContract.validate(frame)
    assert result.valid is False
    assert "close" in result.invalid_columns


def test_integration_health_reports_ready_payload():
    health = IntegrationHealth()
    result = health.check_payload({"symbol": "ABC", "df": valid_frame()})
    assert result["status"] == "healthy"
    assert result["contract"]["valid"] is True


def test_integration_health_empty_check_is_deterministic():
    result = IntegrationHealth().check_empty()
    assert result["status"] == "healthy"
    assert result["contract"]["validator"] == "available"
