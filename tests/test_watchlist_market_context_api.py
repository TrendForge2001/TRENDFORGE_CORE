from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeWatchlists:
    def __init__(self):
        self.rows = {}

    def summary(self):
        return {
            "status": "ready",
            "watchlist_count": 1,
            "symbol_count": 1,
            "entry_count": 1,
            "watchlists": [
                {
                    "name": "Swing",
                    "count": 1,
                    "symbols": ["TCS"],
                }
            ],
        }

    def get(self, name):
        return {
            "status": "ready",
            "name": name,
            "count": 1,
            "symbols": ["TCS"],
            "entries": [
                {
                    "watchlist": name,
                    "symbol": "TCS",
                    "priority": 3,
                }
            ],
        }

    def upsert(self, name, **fields):
        self.rows[(name, fields["symbol"])] = dict(fields)
        return {
            "status": "saved",
            "watchlist": name,
            "entry": {
                "watchlist": name,
                **fields,
            },
        }

    def update(self, name, symbol, **fields):
        if symbol == "MISSING":
            raise KeyError("missing")
        return {
            "status": "updated",
            "watchlist": name,
            "entry": {
                "watchlist": name,
                "symbol": symbol,
                **fields,
            },
        }

    def remove(self, name, symbol):
        return {
            "status": "removed",
            "watchlist": name,
            "symbol": symbol,
        }

    def delete(self, name):
        return {
            "status": "deleted",
            "watchlist": name,
            "removed_entries": 1,
        }

    def close(self):
        pass


class FakeMarketContext:
    def __init__(self):
        self.calls = []

    def snapshot(self, kind):
        return {
            "status": "ready",
            "kind": kind,
            "universe": "NIFTY 500",
            "snapshot_sample_size": 100,
        }

    def refresh(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "ready",
            "universe": "NIFTY 500",
            "requested_symbols": kwargs["limit"],
            "analyzed_symbols": kwargs["limit"],
            "coverage_pct": 100.0,
            "breadth": {"direction": "BULLISH"},
            "regime": {"regime": "BULLISH"},
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.watchlists = FakeWatchlists()
        self.market = FakeMarketContext()

    def watchlist_dashboard_service(self):
        return self.watchlists

    def market_context_service(self):
        return self.market


def test_watchlist_read_contracts():
    client = TestClient(create_app(Factory()))

    summary = client.get("/watchlists")
    detail = client.get("/watchlists/Swing")

    assert summary.status_code == 200
    assert summary.json()["watchlist_count"] == 1
    assert detail.status_code == 200
    assert detail.json()["symbols"] == ["TCS"]


def test_watchlist_mutation_contracts():
    client = TestClient(create_app(Factory()))

    created = client.post(
        "/watchlists/Swing/symbols",
        json={
            "symbol": "tcs",
            "priority": 4,
            "target": 3300,
            "stoploss": 3000,
        },
    )
    assert created.status_code == 200
    assert created.json()["entry"]["symbol"] == "TCS"

    updated = client.put(
        "/watchlists/Swing/symbols/TCS",
        json={"priority": 5, "notes": "promoted"},
    )
    assert updated.status_code == 200
    assert updated.json()["entry"]["priority"] == 5

    removed = client.delete(
        "/watchlists/Swing/symbols/TCS"
    )
    assert removed.status_code == 200
    assert removed.json()["status"] == "removed"

    deleted = client.delete("/watchlists/Swing")
    assert deleted.status_code == 200
    assert deleted.json()["removed_entries"] == 1


def test_watchlist_update_missing_symbol_is_404():
    client = TestClient(create_app(Factory()))

    response = client.put(
        "/watchlists/Swing/symbols/MISSING",
        json={"priority": 2},
    )

    assert response.status_code == 404


def test_market_context_snapshot_contracts():
    client = TestClient(create_app(Factory()))

    breadth = client.get("/market/breadth")
    regime = client.get("/market/regime")

    assert breadth.status_code == 200
    assert breadth.json()["kind"] == "breadth"
    assert regime.status_code == 200
    assert regime.json()["kind"] == "regime"


def test_market_context_refresh_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/market/context/refresh",
        json={
            "limit": 100,
            "period": "1y",
            "interval": "1d",
            "refresh_universe": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["coverage_pct"] == 100.0
    assert factory.market.calls[0]["limit"] == 100


def test_market_context_refresh_validates_limit():
    client = TestClient(create_app(Factory()))

    response = client.post(
        "/market/context/refresh",
        json={"limit": 10},
    )

    assert response.status_code == 422
