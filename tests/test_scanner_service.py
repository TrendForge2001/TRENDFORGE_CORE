from __future__ import annotations

import pytest

from api.scanner_service import ScannerService


class StubOrchestrator:
    def health(self):
        return {"status": "healthy", "engines_count": 1}


class StubPipeline:
    def __init__(self):
        self.orchestrator = StubOrchestrator()
        self.calls = []

    def analyze(self, symbol, **kwargs):
        self.calls.append(("analyze", symbol, kwargs))
        return {"symbol": symbol, "signal": "BUY"}

    def analyze_many(self, symbols, **kwargs):
        self.calls.append(("analyze_many", symbols, kwargs))
        return {"top_picks": symbols[:1], "scanned_count": len(symbols)}


def test_service_requires_pipeline():
    with pytest.raises(ValueError, match="FullScannerPipeline"):
        ScannerService(None)


def test_scan_delegates_without_own_engine_execution():
    pipeline = StubPipeline()
    service = ScannerService(pipeline)

    result = service.scan("ABC", period="3mo", interval="1h", capital=50000,
                          fundamentals={"roe": 20})

    assert result == {"symbol": "ABC", "signal": "BUY"}
    assert pipeline.calls == [
        ("analyze", "ABC", {
            "period": "3mo",
            "interval": "1h",
            "capital": 50000,
            "fundamentals": {"roe": 20},
        })
    ]


def test_scan_many_delegates_to_pipeline():
    pipeline = StubPipeline()
    service = ScannerService(pipeline)

    result = service.scan_many(["ABC", "XYZ"], period="1mo", interval="15m",
                               capital=10000, top_n=5)

    assert result["scanned_count"] == 2
    assert pipeline.calls == [
        ("analyze_many", ["ABC", "XYZ"], {
            "period": "1mo",
            "interval": "15m",
            "capital": 10000,
            "top_n": 5,
        })
    ]


def test_health_exposes_pipeline_and_orchestrator_health():
    service = ScannerService(StubPipeline())
    result = service.health()

    assert result["status"] == "healthy"
    assert result["pipeline"] == "StubPipeline"
    assert result["orchestrator"]["status"] == "healthy"
    assert result["orchestrator"]["engines_count"] == 1



def test_health_degrades_when_orchestrator_is_unavailable():
    class BrokenOrchestrator:
        def health(self):
            return {"status": "degraded", "error": "engine unavailable"}

    pipeline = StubPipeline()
    pipeline.orchestrator = BrokenOrchestrator()
    result = ScannerService(pipeline).health()

    assert result["status"] == "degraded"
    assert result["orchestrator"]["error"] == "engine unavailable"


def test_health_preserves_configured_as_not_runtime_healthy():
    class ConfiguredOrchestrator:
        def health(self):
            return {"status": "configured"}

    pipeline = StubPipeline()
    pipeline.orchestrator = ConfiguredOrchestrator()

    result = ScannerService(pipeline).health()

    assert result["status"] == "configured"
    assert result["orchestrator"]["status"] == "configured"
