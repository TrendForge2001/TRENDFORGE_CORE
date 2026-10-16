from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Factory:
    def market_day_operations_scheduler(self):
        raise RuntimeError("operations composition failed")

    def import_fundamentals_if_configured(self):
        return {"status": "not_configured"}


def test_operations_composition_failure_does_not_block_app_startup():
    app = create_app(
        Factory(),
        database_initializer=lambda: {
            "status": "initialized",
        },
    )

    with TestClient(app) as client:
        root = client.get("/")
        state = dict(
            client.app.state.market_day_operations_scheduler
        )

    assert root.status_code == 200
    assert state["status"] == "failed"
    assert "operations composition failed" in state["error"]
