from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_market_data_contract_is_ohlcv_boundary_and_engine_contract_is_payload_boundary():
    market = _read("core/data_contract.py")
    engine = _read("engines/input_contract.py")
    assert "class MarketDataContract" in market
    assert "REQUIRED_OHLCV" in market
    assert "class EngineInputContract" in engine
    assert 'REQUIRED = ("symbol", "df")' in engine


def test_engine_input_contract_does_not_duplicate_full_ohlcv_validation():
    engine = _read("engines/input_contract.py")
    assert "required_ohlcv_columns_missing" not in engine
    assert "high_below_low_detected" not in engine
    assert "negative_volume_detected" not in engine


def test_pipeline_contract_remains_separate_from_data_validation_contract():
    pipeline = _read("tests/test_pipeline_contracts.py")
    market = _read("core/data_contract.py")
    assert "FullScannerPipeline" in pipeline
    assert "MarketDataContract" in market


def test_domain_provider_contracts_remain_separate_from_market_data_contract():
    providers = _read("providers/__init__.py")
    market = _read("core/data_contract.py")
    assert "class NewsProvider" in providers
    assert "class CorporateActionProvider" in providers
    assert "class MarketDataContract" in market
