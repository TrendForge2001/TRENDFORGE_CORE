"""Contract tests for the canonical provider -> scanner -> engine pipeline."""

from __future__ import annotations

import unittest

import pandas as pd

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from indicators.indicator_engine import IndicatorEngine
from models.signal import Signal
from providers.market_data_provider import MarketDataProvider
from scanner.full_pipeline import FullScannerPipeline


class FakeProvider(MarketDataProvider):
    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        return pd.DataFrame({
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
        })


class FakeIndicatorEngine:
    def calculate(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
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
    def make_pipeline(self) -> FullScannerPipeline:
        return FullScannerPipeline(
            FakeProvider(),
            orchestrator=EngineOrchestrator(engines=[FakeEngine()]),
            indicator_engine=FakeIndicatorEngine(),
        )

    def test_provider_contract_returns_dataframe(self) -> None:
        candles = FakeProvider().candles("RELIANCE")
        self.assertIsInstance(candles, pd.DataFrame)
        self.assertEqual(list(candles.columns), ["open", "high", "low", "close", "volume"])

    def test_full_pipeline_prepares_canonical_stock_contract(self) -> None:
        result = self.make_pipeline().analyze("RELIANCE")
        self.assertTrue(result["passed"])
        self.assertEqual(result["symbol"], "RELIANCE")
        self.assertTrue(result["eligible"])
        self.assertEqual(result["engines"]["Fake Engine"]["metrics"]["symbol"], "RELIANCE")

    def test_full_pipeline_propagates_period_interval_capital(self) -> None:
        class RecordingProvider(FakeProvider):
            def candles(self, symbol, period="6mo", interval="1d"):
                self.call = (symbol, period, interval)
                return super().candles(symbol, period, interval)

        provider = RecordingProvider()
        pipeline = FullScannerPipeline(
            provider,
            orchestrator=EngineOrchestrator(engines=[FakeEngine()]),
            indicator_engine=FakeIndicatorEngine(),
        )
        result = pipeline.analyze("RELIANCE", period="3mo", interval="1h", capital=50000)
        self.assertTrue(result["passed"])
        self.assertEqual(provider.call, ("RELIANCE", "3mo", "1h"))

    def test_analyze_many_deduplicates_and_ranks(self) -> None:
        result = self.make_pipeline().analyze_many(
            ["reliance", "RELIANCE", "TCS"], top_n=1
        )
        self.assertEqual(result["scanned_count"], 2)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["top_picks"]), 1)
        self.assertEqual({item["symbol"] for item in result["results"]}, {"RELIANCE", "TCS"})

    def test_analyze_many_converts_provider_failure_to_error_result(self) -> None:
        class FailingProvider(FakeProvider):
            def candles(self, symbol, period="6mo", interval="1d"):
                if symbol == "BAD":
                    raise RuntimeError("market data failure")
                return super().candles(symbol, period, interval)

        pipeline = FullScannerPipeline(
            FailingProvider(),
            orchestrator=EngineOrchestrator(engines=[FakeEngine()]),
            indicator_engine=FakeIndicatorEngine(),
        )
        result = pipeline.analyze_many(["GOOD", "BAD"])
        bad = next(item for item in result["rejected"] if item["symbol"] == "BAD")
        self.assertEqual(bad["signal"], "ERROR")
        self.assertFalse(bad["eligible"])

    def test_signal_model_is_unchanged(self) -> None:
        signal = Signal("RELIANCE", "BUY", 82.0, 82.0, entry=102.0, stoploss=98.0)
        self.assertEqual(signal.symbol, "RELIANCE")
        self.assertEqual(signal.signal, "BUY")
        self.assertEqual(signal.entry, 102.0)

    def test_pipeline_requires_provider(self) -> None:
        with self.assertRaises(ValueError):
            FullScannerPipeline(None)


if __name__ == "__main__":
    unittest.main()
