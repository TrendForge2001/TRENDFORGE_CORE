"""Contract tests for the provider -> scanner -> engine pipeline.

These tests use only in-memory fakes, so they do not require market credentials
or network access. They protect the architecture while provider integration is
validated separately.
"""

from __future__ import annotations

import unittest

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from models.signal import Signal
from providers.market_data_provider import MarketDataProvider
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider(MarketDataProvider):
    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        return pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 1200],
            }
        )


class FakeIndicatorEngine:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame["ATR"] = 2.0
        frame["RSI"] = 60.0
        frame["ADX"] = 30.0
        frame["RVOL"] = 1.5
        frame["VWAP"] = frame["close"]
        return frame

    def latest(self, frame: pd.DataFrame) -> dict[str, float]:
        return frame.iloc[-1].to_dict()


class FakeEngine(BaseEngine):
    NAME = "Fake Engine"
    mandatory = True

    def evaluate(self, stock: dict) -> EngineResult:
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=80.0,
            confidence=80.0,
            grade="A",
            max_score=100.0,
            metrics={"symbol": stock["symbol"]},
        )


class PipelineContractTests(unittest.TestCase):
    def test_provider_contract_returns_dataframe(self) -> None:
        candles = FakeProvider().candles("RELIANCE")
        self.assertIsInstance(candles, pd.DataFrame)
        self.assertEqual(list(candles.columns), ["open", "high", "low", "close", "volume"])

    def test_orchestrator_aggregates_engine_results(self) -> None:
        result = EngineOrchestrator(engines=[FakeEngine()]).evaluate({"symbol": "RELIANCE"})
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 80.0)
        self.assertEqual(result["confidence"], 80.0)
        self.assertIn("Fake Engine", result["engines"])

    def test_signal_model_is_serializable_by_attributes(self) -> None:
        signal = Signal("RELIANCE", "BUY", 82.0, 82.0, entry=102.0, stoploss=98.0)
        self.assertEqual(signal.symbol, "RELIANCE")
        self.assertEqual(signal.signal, "BUY")
        self.assertEqual(signal.entry, 102.0)

    def test_full_pipeline_prepares_canonical_stock_contract(self) -> None:
        pipeline = FullScannerPipeline(
            FakeProvider(),
            orchestrator=EngineOrchestrator(engines=[FakeEngine()]),
            indicator_engine=FakeIndicatorEngine(),
        )
        result = pipeline.analyze("RELIANCE")
        self.assertTrue(result["passed"])
        self.assertEqual(result["engines"]["Fake Engine"]["metrics"]["symbol"], "RELIANCE")


if __name__ == "__main__":
    unittest.main()
