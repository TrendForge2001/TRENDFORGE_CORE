from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeBacktests:
    def __init__(self):
        self.calls = []

    def readiness(self):
        return {
            "status": "ready",
            "strategy": "EMA20_50_RSI",
            "strategy_version": "R68.4-v1",
            "broker_orders_allowed": False,
        }

    def history(self, *, limit=50, symbol=None):
        return {
            "status": "ready",
            "returned": 1,
            "runs": [
                {
                    "run_id": "bt-1",
                    "symbol": symbol or "TCS",
                    "return_pct": 10.0,
                }
            ],
        }

    def run(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": "completed",
            "run_id": kwargs.get("run_id") or "bt-new",
            "symbol": kwargs["symbol"],
            "metrics": {
                "return_pct": 12.0,
                "total_trades": 3,
            },
            "trades": [],
            "equity_curve": [],
            "safety": {
                "broker_orders_allowed": False,
            },
        }

    def get(self, run_id):
        if run_id == "missing":
            from services.backtest_service import (
                BacktestNotFoundError,
            )
            raise BacktestNotFoundError("missing")
        return {
            "status": "completed",
            "run_id": run_id,
            "symbol": "TCS",
            "metrics": {"return_pct": 12.0},
            "trades": [],
            "equity_curve": [],
        }

    def close(self):
        pass


class Factory:
    def __init__(self):
        self.backtests = FakeBacktests()

    def backtest_service(self):
        return self.backtests


def test_backtest_readiness_and_history_contracts():
    client = TestClient(create_app(Factory()))

    readiness = client.get("/backtests/readiness")
    history = client.get(
        "/backtests",
        params={"limit": 10, "symbol": "tcs"},
    )

    assert readiness.status_code == 200
    assert readiness.json()["strategy_version"] == "R68.4-v1"
    assert readiness.json()["broker_orders_allowed"] is False

    assert history.status_code == 200
    assert history.json()["returned"] == 1
    assert history.json()["runs"][0]["symbol"] == "tcs"


def test_backtest_run_normalizes_symbol_and_forwards_parameters():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/backtests",
        json={
            "symbol": "tcs",
            "period": "2y",
            "interval": "1d",
            "capital": 150000,
            "rsi_threshold": 61,
            "ema_proximity_pct": 1.5,
            "cost_bps": 5,
            "slippage_bps": 3,
            "run_id": "bt-api",
        },
    )

    assert response.status_code == 200
    assert response.json()["run_id"] == "bt-api"
    assert factory.backtests.calls[0]["symbol"] == "TCS"
    assert factory.backtests.calls[0]["cost_bps"] == 5.0


def test_backtest_run_validates_contract():
    client = TestClient(create_app(Factory()))

    response = client.post(
        "/backtests",
        json={
            "symbol": "TCS",
            "period": "6mo",
        },
    )

    assert response.status_code == 422


def test_backtest_detail_contract_and_not_found():
    client = TestClient(create_app(Factory()))

    detail = client.get("/backtests/bt-1")
    missing = client.get("/backtests/missing")

    assert detail.status_code == 200
    assert detail.json()["run_id"] == "bt-1"
    assert missing.status_code == 404
