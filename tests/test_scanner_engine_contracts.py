"""Contract tests for the canonical scanner engine stage."""
from __future__ import annotations

import pandas as pd

from engines.base_engine import EngineResult
from scanner.scanner_engine import ScannerEngine


class Ready:
    def check(self, stock):
        class Result:
            ready = True
            reasons = ()
            warnings = ()

            def as_dict(self):
                return {"ready": True, "reasons": [], "warnings": []}

        return Result()


class Orchestrator:
    def evaluate(self, stock):
        return {
            "score": 82.0,
            "confidence": 78.0,
            "passed": True,
            "signal": type("SignalResult", (), {"signal": "BUY", "warnings": []})(),
            "engines": {
                "Technical Engine": EngineResult(
                    "Technical Engine", True, 82.0, 78.0, "A"
                )
            },
        }


def frame():
    rows = 40
    return pd.DataFrame(
        {
            "open": [100.0 + i for i in range(rows)],
            "high": [102.0 + i for i in range(rows)],
            "low": [99.0 + i for i in range(rows)],
            "close": [101.0 + i for i in range(rows)],
            "volume": [1000] * rows,
        }
    )


def test_scanner_engine_converts_payload_to_canonical_result():
    engine = ScannerEngine(
        orchestrator=Orchestrator(),
        readiness_checker=Ready(),
        max_workers=2,
    )
    result = engine.scan_payload({"symbol": "AAA", "df": frame()})
    assert result.symbol == "AAA"
    assert result.signal == "BUY"
    assert result.overall_score == 82.0
    assert result.confidence == 78.0
    assert result.passed is True
    assert result.readiness["ready"] is True


def test_scanner_engine_isolates_symbol_failures_in_batch():
    class FailingOrchestrator(Orchestrator):
        def evaluate(self, stock):
            if stock["symbol"] == "BBB":
                raise RuntimeError("engine failed")
            return super().evaluate(stock)

    engine = ScannerEngine(
        orchestrator=FailingOrchestrator(),
        readiness_checker=Ready(),
        max_workers=2,
    )
    results = engine.scan_payload_many(
        {"AAA": {"symbol": "AAA", "df": frame()}, "BBB": {"symbol": "BBB", "df": frame()}}
    )
    by_symbol = {item.symbol: item for item in results}
    assert by_symbol["AAA"].signal == "BUY"
    assert by_symbol["BBB"].signal == "IGNORE"
    assert any("engine_evaluation_error" in reason for reason in by_symbol["BBB"].reasons)
