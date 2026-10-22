from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app
from api.production_runtime import secure_application
from services.paper_trading_service import (
    PaperTradingDisabledError,
    PaperTradingKillSwitchError,
)


class FakePaperService:
    def __init__(self):
        self.restored = 0
        self.closed = False
        self.kill = False
        self.opened = []

    def restore_open(self):
        self.restored += 1
        return 1

    def health(self):
        return {
            "status": "ready",
            "mode": "paper_only",
            "broker_orders_allowed": False,
            "enabled": True,
            "kill_switch": self.kill,
            "environment_kill_switch": False,
            "runtime_kill_switch": self.kill,
            "can_open_new_positions": not self.kill,
            "open_positions": len(self.opened),
            "restored_open_trades": 1,
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

    def open(self, request):
        if self.kill:
            raise PaperTradingKillSwitchError(
                "Paper trading kill switch is active"
            )
        self.opened.append(request.symbol)
        return {
            "status": "opened",
            "trade_id": 9,
            **self.snapshot(),
        }

    def monitor(self, quotes):
        return {
            "status": "monitored",
            "closed": [],
            **self.snapshot(),
        }

    def set_runtime_kill_switch(self, enabled):
        self.kill = bool(enabled)
        return self.health()

    def close(self):
        self.closed = True


class Factory:
    def __init__(self, paper):
        self.paper = paper

    def paper_trading_service(self):
        return self.paper

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def app_for(paper):
    return create_app(
        Factory(paper),
        database_initializer=lambda: {
            "status": "initialized",
        },
    )


def test_canonical_lifespan_restores_and_closes_paper_runtime():
    paper = FakePaperService()
    app = app_for(paper)

    with TestClient(app) as client:
        readiness = client.get("/paper/readiness")
        assert readiness.status_code == 200
        assert readiness.json()["restore"] == {
            "status": "restored",
            "open_trades": 1,
        }

    assert paper.restored == 1
    assert paper.closed is True


def test_canonical_paper_routes_open_monitor_snapshot_and_kill_switch():
    paper = FakePaperService()
    app = app_for(paper)

    with TestClient(app) as client:
        opened = client.post(
            "/paper/open",
            json={
                "symbol": "tcs",
                "side": "BUY",
                "quantity": 1,
                "price": 3000,
                "stoploss": 2950,
                "target2": 3100,
            },
        )
        assert opened.status_code == 200
        assert opened.json()["trade_id"] == 9
        assert paper.opened == ["TCS"]

        monitored = client.post(
            "/paper/monitor",
            json={"quotes": {"tcs": 3010}},
        )
        assert monitored.status_code == 200

        snapshot = client.get("/paper")
        assert snapshot.status_code == 200
        assert snapshot.json()["mode"] == "paper_only"

        killed = client.post(
            "/paper/kill-switch",
            json={"enabled": True},
        )
        assert killed.status_code == 200
        assert killed.json()["kill_switch"] is True

        blocked = client.post(
            "/paper/open",
            json={
                "symbol": "INFY",
                "side": "BUY",
                "quantity": 1,
                "price": 1500,
                "stoploss": 1450,
                "target2": 1600,
            },
        )
        assert blocked.status_code == 423


def test_production_paper_entry_requires_storage_but_monitor_and_kill_remain_available(
    monkeypatch,
):
    paper = FakePaperService()
    monkeypatch.delenv("TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION", raising=False)
    monkeypatch.setenv(
        "TRENDFORGE_ADMIN_API_KEY",
        "p" * 40,
    )
    monkeypatch.setattr(
        "api.production_runtime.storage_health",
        lambda: {
            "verified_persistent": False,
            "status": "ephemeral_or_unverified",
        },
    )

    app = secure_application(app_for(paper))

    with TestClient(app) as client:
        denied = client.get("/paper")
        assert denied.status_code == 401

        headers = {
            "X-TrendForge-Admin-Key": "p" * 40,
        }
        allowed = client.post(
            "/paper/open",
            json={
                "symbol": "TCS",
                "side": "BUY",
                "quantity": 1,
                "price": 3000,
                "stoploss": 2950,
                "target2": 3100,
            },
            headers=headers,
        )
        assert allowed.status_code == 423
        assert allowed.json()["error_code"] == "PAPER_STORAGE_REQUIRED"
        assert paper.opened == []

        assert client.post("/paper/monitor", json={"quotes": {}}, headers=headers).status_code == 200
        killed = client.post("/paper/kill-switch", json={"enabled": True}, headers=headers)
        assert killed.status_code == 200
        assert killed.json()["kill_switch"] is True

        readiness = client.get(
            "/paper/readiness",
            headers=headers,
        )
        assert readiness.status_code == 200
        assert readiness.json()["broker_orders_allowed"] is False


def test_disabled_service_maps_to_503():
    class Disabled(FakePaperService):
        def open(self, request):
            raise PaperTradingDisabledError(
                "Paper trading is disabled by production configuration"
            )

    with TestClient(app_for(Disabled())) as client:
        response = client.post(
            "/paper/open",
            json={
                "symbol": "TCS",
                "quantity": 1,
                "price": 3000,
            },
        )

    assert response.status_code == 503
