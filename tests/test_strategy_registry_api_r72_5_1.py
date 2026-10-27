from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class Factory:
    def technical_trading_service(self):
        return None


def test_strategy_registry_api_lists_without_starting_runtime_work():
    client = TestClient(create_app(Factory()))
    response = client.get("/technical/strategies")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "source-six-with-intraday-shorts-v2"
    assert payload["count"] == 8
    assert payload["readiness"]["scan_started"] is False
    assert payload["readiness"]["paper_orders_created"] is False


def test_strategy_registry_api_filters_and_returns_detail():
    client = TestClient(create_app(Factory()))
    filtered = client.get(
        "/technical/strategies",
        params={"mode": "intraday", "source": "template"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 0
    assert all(
        row["source"] == "template"
        for row in filtered.json()["strategies"]
    )

    detail = client.get(
        "/technical/strategies/tf_swing_ema20_50_rsi_volume"
    )
    assert detail.status_code == 200
    strategy = detail.json()["strategy"]
    assert strategy["source"] == "user_notebook"
    assert strategy["default_interval"] == "1d"


def test_strategy_registry_api_returns_404_for_unknown_id():
    client = TestClient(create_app(Factory()))
    response = client.get("/technical/strategies/not-a-strategy")
    assert response.status_code == 404
