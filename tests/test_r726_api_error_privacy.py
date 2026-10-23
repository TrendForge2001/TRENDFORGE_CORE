"""Provider failures must not become client validation messages or paper prices."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from services.technical_trading_service import TechnicalTradingValidationError


@pytest.mark.parametrize(
    "path,payload,method",
    [
        ("/technical/scan", {"symbols": ["TCS"]}, "scan"),
        ("/technical/backtest", {"symbol": "TCS"}, "backtest"),
    ],
)
def test_technical_provider_value_errors_are_sanitized(path, payload, method, caplog):
    private_detail = "provider-credential-" + "must-remain-private"

    def broken(**_kwargs):
        raise ValueError(private_detail)

    service = SimpleNamespace(**{method: broken})
    factory = SimpleNamespace(technical_trading_service=lambda: service)
    response = TestClient(create_app(factory)).post(path, json=payload)

    assert response.status_code == 503
    assert response.json()["error_code"] == "SERVICE_UNAVAILABLE"
    assert private_detail not in response.text
    assert private_detail not in caplog.text


@pytest.mark.parametrize(
    "path,payload,method",
    [
        ("/technical/scan", {"symbols": ["TCS"]}, "scan"),
        ("/technical/backtest", {"symbol": "TCS"}, "backtest"),
    ],
)
def test_technical_local_validation_remains_actionable(path, payload, method):
    def invalid(**_kwargs):
        raise TechnicalTradingValidationError("No completed candles available")

    service = SimpleNamespace(**{method: invalid})
    factory = SimpleNamespace(technical_trading_service=lambda: service)
    response = TestClient(create_app(factory)).post(path, json=payload)

    assert response.status_code == 422
    assert response.json()["detail"] == "No completed candles available"


@pytest.mark.parametrize("price", ["inf", "-inf", "nan", 0, -1, True, False])
def test_invalid_paper_quotes_are_rejected_before_service_call(price):
    calls = []
    service = SimpleNamespace(monitor=lambda quotes: calls.append(quotes))
    factory = SimpleNamespace(paper_trading_service=lambda: service)
    response = TestClient(create_app(factory)).post(
        "/paper/monitor", json={"quotes": {"TCS": price}}
    )

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("field", ["quantity", "price", "stoploss", "target2"])
def test_boolean_paper_order_numbers_are_rejected_before_service_call(field):
    calls = []
    service = SimpleNamespace(open=lambda order: calls.append(order))
    factory = SimpleNamespace(paper_trading_service=lambda: service)
    order = {"symbol": "TCS", "quantity": 1, "price": 100.0}
    order[field] = True
    response = TestClient(create_app(factory)).post("/paper/open", json=order)

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("symbol", ["../TCS", "TCS SBIN", "<script>", "NSE:TCS"])
def test_invalid_paper_symbol_is_rejected_before_service_call(symbol):
    calls = []
    service = SimpleNamespace(open=lambda order: calls.append(order))
    factory = SimpleNamespace(paper_trading_service=lambda: service)
    response = TestClient(create_app(factory)).post(
        "/paper/open", json={"symbol": symbol, "quantity": 1, "price": 100}
    )
    assert response.status_code == 422
    assert calls == []
