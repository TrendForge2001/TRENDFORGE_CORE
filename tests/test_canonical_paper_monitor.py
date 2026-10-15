from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakePaper:
    def restore_open(self):
        return 0

    def health(self):
        return {
            "status": "ready",
            "mode": "paper_only",
            "broker_orders_allowed": False,
            "enabled": True,
            "kill_switch": False,
            "environment_kill_switch": False,
            "runtime_kill_switch": False,
            "can_open_new_positions": True,
            "open_positions": 0,
            "restored_open_trades": 0,
            "market_open_time_ist": "09:15",
            "entry_cutoff_time_ist": "15:00",
            "force_exit_time_ist": "15:00",
        }

    def snapshot(self):
        return {
            **self.health(),
            "positions": [],
            "unrealized_pnl": 0.0,
            "realized_pnl": 0.0,
            "total_pnl": 0.0,
        }

    def close(self):
        return None


class FakeMonitor:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.started = 0
        self.stopped = 0
        self.ticks = 0
        self.running = False

    async def start(self):
        self.started += 1
        if self.enabled:
            self.running = True
            return True
        return False

    async def stop(self):
        self.stopped += 1
        self.running = False

    def tick(self):
        self.ticks += 1
        return {
            "status": "idle",
            "symbols": [],
            "quotes": {},
            "closed": [],
        }

    def health(self):
        return {
            "status": (
                "running"
                if self.running
                else "disabled"
                if not self.enabled
                else "starting"
            ),
            "enabled": self.enabled,
            "running": self.running,
            "quote_source": "FakeKite",
            "poll_interval_seconds": 15.0,
            "idle_interval_seconds": 30.0,
            "open_position_count": 0,
            "open_symbols": [],
            "iterations": self.ticks,
            "quote_success_count": 0,
            "quote_failure_count": 0,
            "closed_count": 0,
            "last_poll_at": None,
            "last_success_at": None,
            "last_error_at": None,
            "last_error": None,
            "last_symbols": [],
            "last_quotes": {},
            "last_closed": [],
            "broker_orders_allowed": False,
        }


class Factory:
    def __init__(self, monitor):
        self.paper = FakePaper()
        self.monitor = monitor

    def paper_trading_service(self):
        return self.paper

    def paper_quote_monitor(self):
        return self.monitor

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def app_for(monitor):
    return create_app(
        Factory(monitor),
        database_initializer=lambda: {
            "status": "initialized",
        },
    )


def test_canonical_lifespan_starts_and_stops_monitor():
    monitor = FakeMonitor(enabled=True)
    app = app_for(monitor)

    with TestClient(app) as client:
        response = client.get("/paper/monitor-runtime")
        assert response.status_code == 200
        assert response.json()["running"] is True

        readiness = client.get("/paper/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["automatic_monitor"]["running"] is True
        assert readiness.json()["automatic_monitor_start"] == {
            "status": "started"
        }

    assert monitor.started == 1
    assert monitor.stopped == 1


def test_disabled_monitor_is_reported_without_starting_loop():
    monitor = FakeMonitor(enabled=False)
    app = app_for(monitor)

    with TestClient(app) as client:
        readiness = client.get("/paper/readiness").json()

    assert readiness["automatic_monitor"]["status"] == "disabled"
    assert readiness["automatic_monitor_start"] == {
        "status": "disabled"
    }
    assert monitor.started == 1
    assert monitor.stopped == 1


def test_manual_monitor_tick_uses_canonical_monitor():
    monitor = FakeMonitor(enabled=True)

    with TestClient(app_for(monitor)) as client:
        response = client.post("/paper/monitor/tick")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"
    assert monitor.ticks == 1
