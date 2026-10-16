from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeIntelligence:
    def __init__(self):
        self.refresh_calls = []

    def readiness(self):
        return {
            "status": "ready",
            "persisted_events": 2,
            "ai_sentiment": False,
        }

    def events(self, *, domain=None, symbol=None, limit=100):
        return {
            "status": "ready",
            "domain": domain,
            "symbol": symbol.upper() if symbol else None,
            "returned": 1,
            "events": [{"domain": domain or "news"}],
        }

    def summary(self, symbol):
        return {
            "status": "ready",
            "symbol": symbol.upper(),
            "combined_intelligence_score": 3.0,
        }

    def news(self, symbol, *, limit=100):
        return {
            "status": "ready",
            "symbol": symbol.upper(),
            "count": 1,
            "events": [{"headline": "news"}],
        }

    def corporate_actions(self, symbol, *, limit=100):
        return {
            "status": "ready",
            "symbol": symbol.upper(),
            "count": 1,
            "events": [{"headline": "bonus"}],
        }

    def refresh(self, **kwargs):
        self.refresh_calls.append(dict(kwargs))
        return {
            "status": "completed",
            "symbols": kwargs["symbols"],
            "domains": kwargs["domains"],
            "news_events": 1,
            "corporate_action_events": 1,
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.intelligence = FakeIntelligence()

    def intelligence_dashboard_service(self):
        return self.intelligence


def test_intelligence_read_contracts():
    client = TestClient(create_app(Factory()))

    readiness = client.get("/intelligence/readiness")
    events = client.get(
        "/intelligence/events",
        params={"domain": "news", "symbol": "tcs"},
    )
    summary = client.get("/intelligence/tcs/summary")
    news = client.get("/intelligence/tcs/news")
    actions = client.get(
        "/intelligence/tcs/corporate-actions"
    )

    assert readiness.status_code == 200
    assert readiness.json()["ai_sentiment"] is False
    assert events.status_code == 200
    assert events.json()["symbol"] == "TCS"
    assert summary.status_code == 200
    assert summary.json()["symbol"] == "TCS"
    assert news.status_code == 200
    assert actions.status_code == 200


def test_intelligence_refresh_contract_normalizes_symbols():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/intelligence/refresh",
        json={
            "symbols": ["tcs", "INFY"],
            "domains": ["news", "corporate_actions"],
            "days": 90,
        },
    )

    assert response.status_code == 200
    assert factory.intelligence.refresh_calls[0]["symbols"] == [
        "TCS",
        "INFY",
    ]
    assert factory.intelligence.refresh_calls[0]["days"] == 90


def test_intelligence_refresh_validates_domains():
    client = TestClient(create_app(Factory()))

    response = client.post(
        "/intelligence/refresh",
        json={
            "symbols": ["TCS"],
            "domains": ["social_media"],
        },
    )

    assert response.status_code == 422


def test_intelligence_events_validates_domain_from_service():
    class Strict(FakeIntelligence):
        def events(self, **kwargs):
            raise ValueError("domain must be news or corporate_action")

    class StrictFactory:
        def intelligence_dashboard_service(self):
            return Strict()

    client = TestClient(create_app(StrictFactory()))
    response = client.get(
        "/intelligence/events",
        params={"domain": "bad"},
    )
    assert response.status_code == 422
