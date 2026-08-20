from __future__ import annotations

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from api.app import app


def test_root_contract():
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.json()["service"] == "TrendForge Core"


def test_health_contract(monkeypatch):
    class Scanner:
        def analyze(self, *args, **kwargs): return {}
        def analyze_many(self, *args, **kwargs): return {}

    class Application:
        scanner = Scanner()
        def health(self): return {"status": "healthy"}

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_single_scan_uses_scanner_service(monkeypatch):
    class Scanner:
        def analyze(self, symbol, **kwargs):
            return {"symbol": symbol.upper(), "eligible": True}
        def analyze_many(self, *args, **kwargs): return {}

    class Application:
        scanner = Scanner()
        def health(self): return {"status": "healthy"}

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).get("/scan/abc")
    assert response.status_code == 200
    assert response.json()["symbol"] == "ABC"


def test_batch_scan_uses_scanner_service(monkeypatch):
    class Scanner:
        def analyze(self, *args, **kwargs): return {}
        def analyze_many(self, symbols, **kwargs):
            return {"scanned_count": len(symbols), "top_picks": []}

    class Application:
        scanner = Scanner()
        def health(self): return {"status": "healthy"}

    monkeypatch.setattr("api.app.get_application", lambda: Application())
    response = TestClient(app).post("/scan", json={"symbols": ["AAA", "BBB"]})
    assert response.status_code == 200
    assert response.json()["scanned_count"] == 2
