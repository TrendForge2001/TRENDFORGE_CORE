from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeScannerService:
    def scan(self, symbol, **kwargs):
        return {"symbol": symbol, "source": "fake", **kwargs}

    def scan_many(self, symbols, **kwargs):
        return {"symbols": symbols, "source": "fake", **kwargs}

    def health(self):
        return {"status": "healthy"}


class FakeApplicationFactory:
    def scanner_service(self):
        return FakeScannerService()

    def health(self):
        return {"status": "healthy", "composition": "fake"}


def test_health_route_delegates_to_application_factory():
    client = TestClient(create_app(FakeApplicationFactory()))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["composition"] == "fake"


def test_scan_routes_delegate_to_scanner_service():
    client = TestClient(create_app(FakeApplicationFactory()))

    one = client.get("/scan/RELIANCE")
    many = client.post("/scan", json={"symbols": ["RELIANCE", "TCS"]})

    assert one.status_code == 200
    assert one.json()["symbol"] == "RELIANCE"
    assert many.status_code == 200
    assert many.json()["symbols"] == ["RELIANCE", "TCS"]
