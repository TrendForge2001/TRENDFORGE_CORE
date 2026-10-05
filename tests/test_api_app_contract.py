from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.app import app


def test_root_contract():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "TrendForge Core"


def test_health_uses_application_factory(monkeypatch):
    class Application:
        def health(self):
            return {"status": "healthy"}

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_single_scan_uses_scanner_service(monkeypatch):
    calls = []

    class ScannerService:
        def scan(self, symbol, **kwargs):
            calls.append(("single", symbol, kwargs))
            return {"symbol": symbol.upper(), "eligible": True}

    monkeypatch.setattr("api.app.get_scanner_service", lambda: ScannerService())
    response = TestClient(app).get("/scan/abc")
    assert response.status_code == 200
    assert response.json()["symbol"] == "ABC"
    assert calls[0][0] == "single"


def test_batch_scan_uses_scanner_service(monkeypatch):
    calls = []

    class ScannerService:
        def scan_many(self, symbols, **kwargs):
            calls.append((symbols, kwargs))
            return {"scanned_count": len(symbols), "top_picks": []}

    monkeypatch.setattr("api.app.get_scanner_service", lambda: ScannerService())
    response = TestClient(app).post("/scan", json={"symbols": ["AAA", "BBB"]})
    assert response.status_code == 200
    assert response.json()["scanned_count"] == 2
    assert calls[0][0] == ["AAA", "BBB"]
