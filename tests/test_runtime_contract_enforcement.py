from __future__ import annotations

import pandas as pd
import pytest

from engines.engine_orchestrator import EngineOrchestrator
from scanner.full_pipeline import FullScannerPipeline


class Provider:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame

    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        return self.frame.copy()


class IndicatorStub:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame["ATR"] = 1.0
        frame["RSI"] = 60.0
        frame["ADX"] = 25.0
        frame["RVOL"] = 1.0
        frame["VWAP"] = frame["close"]
        return frame

    def latest(self, frame: pd.DataFrame) -> dict:
        return frame.iloc[-1].to_dict()


VALID = pd.DataFrame({
    "open": [100.0, 101.0],
    "high": [102.0, 103.0],
    "low": [99.0, 100.0],
    "close": [101.0, 102.0],
    "volume": [1000.0, 1200.0],
})


def test_market_data_contract_is_enforced_before_indicator_execution():
    invalid = VALID.drop(columns=["volume"])
    pipeline = FullScannerPipeline(Provider(invalid), orchestrator=EngineOrchestrator(), indicator_engine=IndicatorStub())
    with pytest.raises(ValueError, match="required_ohlcv_columns_missing"):
        pipeline.analyze("TEST")


def test_engine_input_contract_is_enforced_before_orchestrator_execution():
    class BadIndicator(IndicatorStub):
        def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
            frame = super().calculate(frame)
            frame["close"] = float("nan")
            return frame

    pipeline = FullScannerPipeline(Provider(VALID), orchestrator=EngineOrchestrator(), indicator_engine=BadIndicator())
    with pytest.raises(ValueError, match="Engine input contract failed"):
        pipeline.analyze("TEST")


def test_valid_payload_carries_engine_input_contract_report():
    pipeline = FullScannerPipeline(Provider(VALID), orchestrator=EngineOrchestrator(), indicator_engine=IndicatorStub())
    stock = pipeline._prepare("TEST", VALID)
    assert stock["engine_input_contract"]["ready"] is True
