from __future__ import annotations

import pandas as pd

from core.data_contract import MarketDataContract
from engines.input_contract import EngineInputContract
from core.integration_health import IntegrationHealth


def candles():
    return pd.DataFrame({
        "open": [10.0, 11.0],
        "high": [12.0, 13.0],
        "low": [9.0, 10.0],
        "close": [11.0, 12.0],
        "volume": [1000, 1200],
    })


def test_main_branch_contract_features_are_present_on_rebuild():
    data = candles()
    contract = MarketDataContract.validate(data)
    assert contract.valid is True
    assert contract.rows == 2

    report = EngineInputContract().validate({"symbol": "ABC", "df": data})
    assert report.ready is True
    assert report.missing == ()
    assert report.invalid == ()


def test_main_branch_integration_health_contract_is_preserved():
    health = IntegrationHealth().check_payload({"symbol": "ABC", "df": candles()})
    assert health["status"] in {"configured", "healthy", "not_ready"}
    assert health["contract"]["valid"] is True
    assert "orchestrator" in health


def test_empty_health_is_provider_independent():
    health = IntegrationHealth().check_empty()
    assert health["status"] == "configured"
    assert health["contract"]["validator"] == "available"
    assert health["readiness"] == "not_checked"
