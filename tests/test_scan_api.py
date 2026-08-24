"""HTTP API contract tests without external market calls."""
from fastapi.testclient import TestClient

from api.scan_api import app


class FakeScanner:
    def scan(self, symbols, capital=0, top_n=20):
        return {"symbols": symbols, "capital": capital, "top_n": top_n, "analyzed_count": len(symbols)}


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert "status" in response.json()


def test_scan_endpoint_with_injected_scanner(monkeypatch):
    import api.scan_api as module
    monkeypatch.setattr(module, "get_scanner", lambda: FakeScanner())
    client = TestClient(app)
    response = client.post("/scan", json={"symbols": ["RELIANCE", "TCS"], "capital": 100000, "top_n": 5})
    assert response.status_code == 200
    assert response.json()["analyzed_count"] == 2


def test_scan_endpoint_rejects_empty_symbols():
    client = TestClient(app)
    response = client.post("/scan", json={"symbols": []})
    assert response.status_code == 422
