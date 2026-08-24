"""Integration tests for the application-facing ScannerService."""
from __future__ import annotations

import pandas as pd

from services.scanner_service import ScannerService


class Provider:
    def historical_data(self, symbol, period="1y", interval="1d", auto_adjust=False):
        rows = 60
        return pd.DataFrame({
            "Open": range(rows), "High": range(1, rows + 1),
            "Low": range(rows), "Close": range(1, rows + 1),
            "Volume": [1000] * rows,
        })


class Scanner:
    def scan_payload_many(self, payloads, capital=0):
        return [type("Result", (), {"symbol": symbol, "score": 50.0, "overall_score": 50.0, "confidence": 70.0, "signal": "BUY"})() for symbol in payloads]


def test_scanner_service_runs_pipeline_with_provider_data():
    service = ScannerService(Provider(), scanner=Scanner())
    result = service.scan(["AAA", "BBB"], top_n=1)
    assert result["universe_size"] == 2
    assert result["market_data_loaded"] == 2
    assert result["analyzed_count"] == 2
    assert len(result["top_picks"]) == 1


def test_scanner_service_rejects_empty_symbol_list():
    service = ScannerService(Provider(), scanner=Scanner())
    try:
        service.scan([])
    except ValueError as exc:
        assert "symbol" in str(exc).lower()
    else:
        raise AssertionError("Expected ValueError")
