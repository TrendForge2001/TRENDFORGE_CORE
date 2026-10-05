"""Rebuild smoke tests for the canonical TrendForge engine chain."""
from __future__ import annotations

import pandas as pd

from engines.engine_orchestrator import EngineOrchestrator


def _stock() -> dict:
    close = pd.Series(range(1, 81), dtype=float)
    frame = pd.DataFrame({
        "open": close - 0.25,
        "high": close + 0.5,
        "low": close - 0.5,
        "close": close,
        "volume": [1000.0] * len(close),
    })
    return {"symbol": "TEST", "df": frame, "capital": 100000.0,
            "atr": 1.0, "close": float(close.iloc[-1])}


def test_orchestrator_constructs_with_all_contracted_engines():
    orchestrator = EngineOrchestrator()
    names = [engine.__class__.__name__ for engine in orchestrator.engines]
    assert len(names) == 8
    assert "ContractedMarketRegimeEngine" in names
    assert "ContractedSectorEngine" in names
    assert "ContractedBigSharkEngine" in names
    assert "ContractedTechnicalEngine" in names
    assert "ContractedPriceActionEngine" in names
    assert "ContractedRiskEngine" in names


def test_invalid_global_input_fails_closed():
    result = EngineOrchestrator().evaluate({"symbol": "TEST"})
    assert result["passed"] is False
    assert result["input_contract"]["ready"] is False


def test_valid_ohlcv_reaches_full_chain_without_orchestrator_exception():
    result = EngineOrchestrator().evaluate(_stock())
    assert "engines" in result
    assert "signal" in result
    assert "input_contract" in result
    assert result["input_contract"]["ready"] is True


def test_health_reports_eight_engine_pipeline():
    health = EngineOrchestrator().health()
    assert health["status"] == "configured"
    assert health["engine_count"] == 8
