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


class FakePaperRuntime:
    def __init__(self): self.opened=False
    def open(self, request): self.opened=True; return 7
    def monitor(self, quotes): return []
    def snapshot(self): return {"open_positions":1 if self.opened else 0,"positions":[],"unrealized_pnl":0.0,"realized_pnl":0.0,"total_pnl":0.0}

class FakeKite:
    def is_logged_in(self): return True
    def holdings(self): return [{"tradingsymbol":"TCS","exchange":"NSE","quantity":5,"average_price":3000,"last_price":3100}]
    def positions(self): return [{"tradingsymbol":"INFY","exchange":"NSE","quantity":-2,"average_price":1600,"last_price":1650,"product":"MIS"}]


def test_paper_endpoints(monkeypatch):
    import api.scan_api as module
    fake = FakePaperRuntime()
    with TestClient(app) as client:
        monkeypatch.setattr(module, "_paper_runtime", fake)
        opened=client.post("/paper/open", json={"symbol":"TCS","quantity":1,"price":3000,"side":"BUY"})
        assert opened.status_code==200
        assert opened.json()["trade_id"]==7
        assert client.post("/paper/monitor", json={"quotes":{"TCS":3010}}).status_code==200
        assert client.get("/paper").status_code==200


def test_portfolio_endpoint_separates_books(monkeypatch):
    import api.scan_api as module
    broker=FakeKite()
    monkeypatch.setattr(module.kite_provider, "is_logged_in", broker.is_logged_in)
    monkeypatch.setattr(module.kite_provider, "holdings", broker.holdings)
    monkeypatch.setattr(module.kite_provider, "positions", broker.positions)
    with TestClient(app) as client:
        response=client.get("/portfolio")
    assert response.status_code==200
    body=response.json()
    assert len(body["holdings"])==1 and body["holdings"][0]["symbol"]=="TCS"
    assert len(body["positions"])==1 and body["positions"][0]["quantity"]==-2


def test_portfolio_endpoint_requires_kite_session(monkeypatch):
    import api.scan_api as module
    monkeypatch.setattr(module.kite_provider, "is_logged_in", lambda: False)
    with TestClient(app) as client:
        assert client.get("/portfolio").status_code==503
