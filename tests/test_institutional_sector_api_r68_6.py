from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeService:
    def __init__(self):
        self.institutional_calls = []
        self.sector_calls = []

    def readiness(self):
        return {
            "status": "ready",
            "institutional_engine": "Big Shark Engine",
            "sector_engine": "Sector Engine",
            "trade_signal": False,
        }

    def institutional_latest(self, *, limit=100):
        return {
            "status": "ready",
            "returned": 1,
            "snapshots": [
                {
                    "symbol": "TCS",
                    "score": 72.0,
                }
            ],
        }

    def institutional(self, symbol):
        return {
            "status": "ready",
            "symbol": symbol.upper(),
            "score": 72.0,
        }

    def refresh_institutional(self, *, symbols):
        self.institutional_calls.append(list(symbols))
        return {
            "status": "ready",
            "requested_symbols": len(symbols),
            "completed_symbols": len(symbols),
        }

    def sector_strength(self):
        return {
            "status": "ready",
            "sector_count": 2,
            "sectors": [
                {"rank": 1, "sector": "IT", "score": 80},
                {"rank": 2, "sector": "BANK", "score": 60},
            ],
        }

    def refresh_sector_strength(self, **kwargs):
        self.sector_calls.append(dict(kwargs))
        return {
            "status": "ready",
            "requested_symbols": kwargs["limit"],
            "sector_count": 2,
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.service = FakeService()

    def institutional_sector_service(self):
        return self.service


def test_institutional_read_contracts():
    client = TestClient(create_app(Factory()))

    readiness = client.get("/institutional/readiness")
    latest = client.get("/institutional")
    symbol = client.get("/institutional/tcs")

    assert readiness.status_code == 200
    assert readiness.json()["trade_signal"] is False
    assert latest.status_code == 200
    assert latest.json()["returned"] == 1
    assert symbol.status_code == 200
    assert symbol.json()["symbol"] == "TCS"


def test_institutional_refresh_normalizes_symbols():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/institutional/refresh",
        json={"symbols": ["tcs", "INFY"]},
    )

    assert response.status_code == 200
    assert factory.service.institutional_calls[0] == [
        "TCS",
        "INFY",
    ]


def test_sector_strength_read_and_refresh_contracts():
    factory = Factory()
    client = TestClient(create_app(factory))

    read = client.get("/sector-strength")
    refresh = client.post(
        "/sector-strength/refresh",
        json={
            "limit": 100,
            "period": "1y",
            "interval": "1d",
            "refresh_universe": False,
        },
    )

    assert read.status_code == 200
    assert read.json()["sector_count"] == 2
    assert refresh.status_code == 200
    assert factory.service.sector_calls[0]["limit"] == 100


def test_sector_strength_refresh_validates_limit():
    client = TestClient(create_app(Factory()))

    response = client.post(
        "/sector-strength/refresh",
        json={"limit": 10},
    )

    assert response.status_code == 422
