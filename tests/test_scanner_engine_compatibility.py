from __future__ import annotations

import pandas as pd

from engines.engine_orchestrator import EngineOrchestrator
from scanner.scanner_engine import ScannerEngine, ScanResult


class StubOrchestrator:
    def __init__(self):
        self.calls = 0

    def evaluate(self, stock):
        self.calls += 1
        return {
            "passed": True,
            "score": 75.0,
            "confidence": 80.0,
            "engines": {},
            "signal": type("Signal", (), {"signal": "BUY", "warnings": []})(),
        }


class StubReadiness:
    def check(self, stock):
        return type("Readiness", (), {
            "ready": True,
            "reasons": [],
            "warnings": [],
            "as_dict": lambda self: {"ready": True},
        })()


def test_scanner_engine_delegates_single_scan_to_orchestrator():
    orchestrator = StubOrchestrator()
    scanner = ScannerEngine(orchestrator=orchestrator, readiness_checker=StubReadiness())

    result = scanner.scan("ABC", pd.DataFrame({"close": [100.0]}))

    assert isinstance(result, ScanResult)
    assert result.signal == "BUY"
    assert result.score == 75.0
    assert orchestrator.calls == 1


def test_scanner_engine_does_not_execute_individual_engines():
    orchestrator = StubOrchestrator()
    scanner = ScannerEngine(orchestrator=orchestrator, readiness_checker=StubReadiness())

    assert scanner.orchestrator is orchestrator
    assert not hasattr(scanner, "engines")


def test_scanner_engine_rank_is_deterministic():
    results = [
        ScanResult("A", 70, "BUY", confidence=90),
        ScanResult("B", 80, "BUY", confidence=50),
        ScanResult("C", 80, "BUY", confidence=95),
    ]
    ranked = ScannerEngine.rank(results)
    assert [item.symbol for item in ranked] == ["C", "B", "A"]
