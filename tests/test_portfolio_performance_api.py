from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class ReportingService:
    def __init__(self):
        self.synced = False

    def portfolio(self):
        return {
            "status": "ready",
            "scope": "persisted_live_portfolio",
            "count": 1,
            "holdings": [{"symbol": "TCS"}],
            "positions": [],
        }

    def sync_portfolio(self):
        self.synced = True
        return {
            "status": "synced",
            "scope": "live_kite_portfolio",
            "count": 1,
        }

    def pnl_statement(self, *, period):
        return {
            "scope": "paper_trading_closed_trades",
            "period": period,
            "summary": {"net_pnl": 125.0},
            "daily": [],
            "trades": [],
        }

    def performance(self, *, period):
        return {
            "scope": "paper_trading_closed_trades",
            "period": period,
            "summary": {
                "net_pnl": 125.0,
                "win_rate_pct": 60.0,
            },
            "equity_curve": [],
            "daily": [],
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.reporting = ReportingService()

    def portfolio_performance_service(self):
        return self.reporting


def test_portfolio_snapshot_contract():
    client = TestClient(create_app(Factory()))

    response = client.get("/portfolio")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"] == "persisted_live_portfolio"
    assert body["holdings"][0]["symbol"] == "TCS"


def test_portfolio_sync_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post("/portfolio/sync")

    assert response.status_code == 200
    assert response.json()["status"] == "synced"
    assert factory.reporting.synced is True


def test_pnl_period_contract():
    client = TestClient(create_app(Factory()))

    response = client.get("/pnl?period=weekly")

    assert response.status_code == 200
    assert response.json()["period"] == "weekly"
    assert response.json()["summary"]["net_pnl"] == 125.0


def test_performance_period_contract():
    client = TestClient(create_app(Factory()))

    response = client.get("/performance?period=yearly")

    assert response.status_code == 200
    assert response.json()["period"] == "yearly"
    assert response.json()["summary"]["win_rate_pct"] == 60.0


def test_invalid_reporting_period_is_422():
    client = TestClient(create_app(Factory()))

    assert client.get("/pnl?period=quarterly").status_code == 422
    assert (
        client.get("/performance?period=quarterly").status_code
        == 422
    )
