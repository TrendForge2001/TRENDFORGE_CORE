from __future__ import annotations

import pandas as pd

from api.scanner_service import ScannerService
from scanner.full_pipeline import FullScannerPipeline
from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator


class Provider:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def candles(self, symbol: str, period: str, interval: str) -> pd.DataFrame:
        self.calls.append((symbol, period, interval))
        index = pd.date_range("2026-01-01", periods=80, freq="D")
        close = pd.Series(range(100, 180), index=index, dtype=float)
        return pd.DataFrame({
            "open": close - 1,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000.0,
        }, index=index)


class PassingEngine:
    NAME = "Integration Engine"
    mandatory = False

    def evaluate(self, stock):
        assert stock["symbol"] == "TEST"
        assert isinstance(stock["df"], pd.DataFrame)
        return EngineResult(
            engine=self.NAME,
            passed=True,
            score=80.0,
            max_score=100.0,
            confidence=80.0,
            grade="A",
        )


def test_complete_scan_path_provider_to_signal_result():
    provider = Provider()
    orchestrator = EngineOrchestrator(engines=[PassingEngine()])
    pipeline = FullScannerPipeline(provider=provider, orchestrator=orchestrator)
    service = ScannerService(pipeline)

    result = service.scan("test", period="3mo", interval="1d")

    assert provider.calls == [("test", "3mo", "1d")]
    assert result["symbol"] == "TEST"
    assert result["passed"] is True
    assert "Integration Engine" in result["engines"]
    assert result["engine_input_contract"]["ready"] is True
    assert "signal" in result


def test_scan_many_isolates_symbol_failure_and_preserves_successful_results():
    class MixedProvider(Provider):
        def candles(self, symbol, period, interval):
            if symbol.upper() == "BAD":
                raise RuntimeError("provider unavailable")
            return super().candles(symbol, period, interval)

    provider = MixedProvider()
    pipeline = FullScannerPipeline(
        provider=provider,
        orchestrator=EngineOrchestrator(engines=[PassingEngine()]),
    )

    batch = pipeline.analyze_many(["TEST", "BAD", "TEST"], top_n=5)

    assert batch["scanned_count"] == 2
    assert batch["count"] == 1
    assert batch["rejected_count"] == 1
    assert batch["results"][0]["symbol"] == "TEST"
    assert batch["rejected"][0]["symbol"] == "BAD"
