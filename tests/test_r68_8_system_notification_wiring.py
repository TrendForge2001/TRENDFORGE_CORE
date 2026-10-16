from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Producer:
    def __init__(self):
        self.events = []

    def startup_event(self, **kwargs):
        self.events.append(dict(kwargs))
        return {"status": "sent"}

    def health(self):
        return {
            "status": "ready",
            "best_effort": True,
        }


class BrokenPaper:
    def restore_open(self):
        raise RuntimeError("paper restore broken")

    def close(self):
        pass


class BrokenMonitor:
    async def start(self):
        raise RuntimeError("monitor start broken")

    async def stop(self):
        pass


class Factory:
    def __init__(self):
        self.producer = Producer()
        self.paper = BrokenPaper()
        self.monitor = BrokenMonitor()

    def notification_producer_service(self):
        return self.producer

    def paper_trading_service(self):
        return self.paper

    def paper_quote_monitor(self):
        return self.monitor

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def test_startup_failures_emit_system_events_without_blocking_app():
    factory = Factory()
    app = create_app(
        factory,
        database_initializer=lambda: {
            "status": "initialized",
        },
    )

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert [
        event["event_type"]
        for event in factory.producer.events
    ] == [
        "paper_restore_failed",
        "paper_monitor_start_failed",
    ]
    assert all(
        event["severity"] == "ERROR"
        for event in factory.producer.events
    )
    assert all(
        event["deliver"] is True
        for event in factory.producer.events
    )
