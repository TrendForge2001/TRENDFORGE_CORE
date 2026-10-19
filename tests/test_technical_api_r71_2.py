from __future__ import annotations

from fastapi.testclient import TestClient

from api.app import create_app


class FakeTechnicalTrading:
    def __init__(self):
        self.scan_calls = []
        self.backtest_calls = []

    def readiness(self):
        return {
            "status": "ready",
            "version": "R71.2-v1",
            "data_policy": "kite_only",
            "fundamentals_used": False,
            "broker_orders_allowed": False,
        }

    def scan(self, **kwargs):
        self.scan_calls.append(dict(kwargs))
        return {
            "status": "completed",
            "run_id": kwargs.get("run_id") or "tech-scan",
            "mode": kwargs["mode"],
            "buy_candidates": 0,
            "results": [],
            "paper": {
                "status": (
                    "executed"
                    if kwargs.get("execute_paper")
                    else "not_requested"
                ),
                "broker_orders_allowed": False,
            },
        }

    def backtest(self, **kwargs):
        self.backtest_calls.append(dict(kwargs))
        return {
            "status": "completed",
            "run_id": kwargs.get("run_id") or "tech-bt",
            "symbol": kwargs["symbol"],
            "interval": "15m" if kwargs["mode"] == "intraday" else "1d",
            "metrics": {"total_trades": 0, "return_pct": 0.0},
            "trades": [],
            "safety": {
                "fundamentals_used": False,
                "broker_orders_allowed": False,
            },
        }


class Factory:
    def __init__(self):
        self.technical = FakeTechnicalTrading()

    def technical_trading_service(self):
        return self.technical


def test_technical_readiness_contract_is_kite_only():
    client = TestClient(create_app(Factory()))

    response = client.get("/technical/readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["version"] == "R71.2-v1"
    assert payload["data_policy"] == "kite_only"
    assert payload["fundamentals_used"] is False
    assert payload["broker_orders_allowed"] is False


def test_technical_scan_normalizes_symbols_and_forwards_paper_opt_in():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/technical/scan",
        json={
            "symbols": ["reliance", "tcs"],
            "mode": "intraday",
            "period": "60d",
            "top_n": 10,
            "execute_paper": True,
            "run_id": "tech-api",
        },
    )

    assert response.status_code == 200
    call = factory.technical.scan_calls[0]
    assert call["symbols"] == ["RELIANCE", "TCS"]
    assert call["mode"] == "intraday"
    assert call["execute_paper"] is True
    assert response.json()["paper"]["broker_orders_allowed"] is False


def test_technical_backtest_contract():
    factory = Factory()
    client = TestClient(create_app(factory))

    response = client.post(
        "/technical/backtest",
        json={
            "symbol": "sbin",
            "mode": "swing",
            "period": "2y",
            "capital": 150000,
            "cost_bps": 5,
            "slippage_bps": 3,
            "run_id": "tech-bt-api",
        },
    )

    assert response.status_code == 200
    call = factory.technical.backtest_calls[0]
    assert call["symbol"] == "SBIN"
    assert call["mode"] == "swing"
    assert call["cost_bps"] == 5.0
    assert response.json()["safety"]["fundamentals_used"] is False


def test_technical_request_validation_rejects_unknown_mode():
    client = TestClient(create_app(Factory()))

    response = client.post(
        "/technical/backtest",
        json={
            "symbol": "TCS",
            "mode": "positional",
        },
    )

    assert response.status_code == 422
