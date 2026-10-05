"""Integration guards for the canonical ScannerEngine -> Orchestrator path."""
from __future__ import annotations

import pandas as pd

from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from scanner.scanner_engine import ScannerEngine


def _frame(rows: int = 60) -> pd.DataFrame:
    close = [100.0 + i * 0.25 for i in range(rows)]
    return pd.DataFrame({
        "open": close,
        "high": [v + 1 for v in close],
        "low": [v - 1 for v in close],
        "close": close,
        "volume": [100000 + i * 1000 for i in range(rows)],
    })


def test_scanner_uses_supplied_orchestrator() -> None:
    class StubOrchestrator:
        def evaluate(self, stock):
            return {
                "passed": True,
                "score": 88.0,
                "confidence": 91.0,
                "signal": type("Signal", (), {"signal": "WATCHLIST", "warnings": []})(),
                "engines": {},
            }

    scanner = ScannerEngine(orchestrator=StubOrchestrator())
    result = scanner.scan("TEST", _frame())
    assert result.signal == "WATCHLIST"
    assert result.score == 88.0
    assert result.passed is True


def test_orchestrator_rejects_non_engine_result() -> None:
    class BadEngine:
        NAME = "Bad Engine"
        mandatory = True

        def evaluate(self, stock):
            return {"passed": True}

    orchestrator = EngineOrchestrator(engines=[BadEngine()])
    result = orchestrator.evaluate({"symbol": "TEST", "df": _frame()})
    assert result["passed"] is False
    assert result["execution_errors"]
    assert result["failed_mandatory"] == ["Bad Engine"]
    assert result["signal"].signal == "HOLD"


def test_engine_result_contract_is_available() -> None:
    result = EngineResult(
        engine="Test", passed=True, score=80.0, confidence=90.0, grade="B"
    )
    assert result.as_dict()["max_score"] == 100.0
