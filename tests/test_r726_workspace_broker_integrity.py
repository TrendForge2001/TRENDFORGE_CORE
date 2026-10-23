"""Keep the five-tab workspace's broker reads private, truthful and read-only."""

from __future__ import annotations

import json
import secrets
from types import SimpleNamespace

import pandas as pd
import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.admin_auth import ADMIN_API_KEY_HEADER
from api.trading_workspace_router import attach_trading_workspace_routes
from providers.kite_errors import TokenException
from services.trading_workspace_service import TradingWorkspaceService


@pytest.fixture(autouse=True)
def no_broker_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Workspace regression tests must remain offline")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


class Broker:
    def __init__(self):
        self.calls = []
        self.authenticated = True
        self.failures = {}
        self.data = {
            "positions": {"day": [], "net": [{"tradingsymbol": "SBIN", "quantity": 1}]},
            "holdings": [{"tradingsymbol": "TCS", "quantity": 2}],
            "orders": [{"order_id": str(number)} for number in range(60)],
            "margins": {"equity": {"available": {"cash": 2000}}},
        }

    def health(self):
        self.calls.append("health")
        return {"authenticated": self.authenticated}

    def _read(self, name):
        self.calls.append(name)
        if name in self.failures:
            raise self.failures[name]
        return self.data[name]

    def positions(self):
        return self._read("positions")

    def holdings(self):
        return self._read("holdings")

    def orders(self):
        return self._read("orders")

    def margins(self):
        return self._read("margins")

    def place_order(self, **kwargs):
        raise AssertionError("Account monitoring must not place broker orders")

    modify_order = cancel_order = place_order


@pytest.fixture
def session_api(monkeypatch):
    key = secrets.token_hex(24)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    broker = Broker()
    app = FastAPI()
    attach_trading_workspace_routes(
        app,
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=SimpleNamespace(_default_kite=lambda: broker),
    )
    return TestClient(app), broker, {ADMIN_API_KEY_HEADER: key}


@pytest.mark.parametrize("authentication", ["missing", "wrong", "unconfigured"])
def test_private_account_reads_require_real_admin_auth_before_broker_work(
    session_api, monkeypatch, authentication
):
    client, broker, _ = session_api
    headers = {}
    if authentication == "wrong":
        headers[ADMIN_API_KEY_HEADER] = secrets.token_hex(24)
    elif authentication == "unconfigured":
        monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY")
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == (503 if authentication == "unconfigured" else 401)
    assert broker.calls == []
    assert "SBIN" not in response.text


def test_authorized_monitoring_preserves_account_data_and_only_recent_orders(
    session_api,
):
    client, broker, headers = session_api
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["authenticated"] is True
    assert payload["read_only"] is True
    assert payload["broker_orders_allowed"] is False
    assert payload["positions"] == broker.data["positions"]
    assert payload["holdings"] == broker.data["holdings"]
    assert payload["margins"] == broker.data["margins"]
    assert [order["order_id"] for order in payload["orders"]] == [
        str(number) for number in range(10, 60)
    ]
    assert broker.calls == ["health", "positions", "holdings", "orders", "margins"]


@pytest.mark.parametrize("authenticated", [False, "false", 1, None])
def test_only_verified_boolean_authentication_can_read_an_account(
    session_api, authenticated
):
    client, broker, headers = session_api
    broker.authenticated = authenticated
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["authenticated"] is False
    assert payload["positions"] == {}
    assert payload["holdings"] == payload["orders"] == []
    assert broker.calls == ["health"]


@pytest.mark.parametrize("read", ["positions", "holdings", "orders", "margins"])
def test_expired_token_after_cached_health_never_returns_a_ready_or_partial_account(
    session_api, read
):
    client, broker, headers = session_api
    sentinel = secrets.token_hex(24)
    broker.failures[read] = TokenException(sentinel)
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is False
    assert payload["status"] == "unavailable"
    assert payload["positions"] == payload["margins"] == {}
    assert payload["holdings"] == payload["orders"] == []
    assert sentinel not in response.text
    assert broker.calls.count(read) == 1


@pytest.mark.parametrize(
    "book,value",
    [
        ("positions", []),
        ("positions", {"day": [], "net": "unavailable"}),
        ("positions", {"day": [], "net": ["invalid row"]}),
        ("holdings", {"error": "unavailable"}),
        ("holdings", ["invalid row"]),
        ("orders", {"error": "unavailable"}),
        ("orders", ["invalid row"]),
        ("margins", []),
        ("margins", {"equity": {"net": float("inf")}}),
    ],
)
def test_malformed_account_books_fail_without_claiming_an_empty_ready_account(
    session_api, book, value
):
    client, broker, headers = session_api
    broker.data[book] = value
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == 503
    assert "SBIN" not in response.text
    assert "invalid row" not in response.text


def test_account_payload_excludes_nested_transport_credentials(session_api):
    client, broker, headers = session_api
    sentinel = secrets.token_hex(24)
    broker.data["positions"]["access_token"] = sentinel
    broker.data["holdings"][0]["api_secret"] = sentinel
    broker.data["holdings"][0]["instrument_token"] = 123
    broker.data["orders"][-1]["metadata"] = {
        "apiKey": sentinel,
        "request_token": sentinel,
        "token": sentinel,
        "password": sentinel,
        "secret": sentinel,
        "session_token": sentinel,
        "strategy": "fixture",
    }
    broker.data["margins"]["equity"]["transport"] = {
        "Authorization": sentinel,
        "refresh-token": sentinel,
        "available": 2000,
    }
    response = client.get("/workspace/kite-session", headers=headers)
    assert response.status_code == 200
    assert sentinel not in response.text
    payload = response.json()
    assert payload["holdings"][0]["tradingsymbol"] == "TCS"
    assert payload["holdings"][0]["instrument_token"] == 123
    assert payload["orders"][-1]["metadata"] == {"strategy": "fixture"}
    assert payload["margins"]["equity"]["transport"] == {"available": 2000}


class Universe:
    def load(self, index_name):
        return {
            "source": "fixture",
            "members": [
                {"symbol": "TCS", "name": "Test company"},
                {"symbol": "SBIN", "name": "Second company"},
            ],
        }


@pytest.mark.parametrize(
    "quote",
    [
        17,
        ["invalid"],
        {"last_price": True},
        {"last_price": float("inf")},
        {"last_price": 10**500},
    ],
)
def test_invalid_quote_rows_preserve_membership_and_do_not_fabricate_prices(quote):
    service = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=Universe(),
        provider_factory=SimpleNamespace(
            quote=lambda: SimpleNamespace(
                safe_quote=lambda instruments: {
                    "NSE:TCS": quote,
                    "NSE:SBIN": {"last_price": 120, "ohlc": {"close": 100}},
                },
            )
        ),
    )
    payload = service.watchlist("NIFTY 50")
    assert payload["count"] == 2
    assert payload["status"] == "degraded"
    assert payload["quoted_count"] == 1
    assert payload["rows"][0]["ltp"] is None
    assert payload["rows"][1]["day_change_pct"] == 20.0
    json.dumps(payload, allow_nan=False)


def test_invalid_ohlc_does_not_discard_a_valid_live_price_or_constituents():
    service = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=Universe(),
        provider_factory=SimpleNamespace(
            quote=lambda: SimpleNamespace(
                safe_quote=lambda instruments: {
                    "NSE:TCS": {"last_price": 100, "ohlc": ["invalid"]}
                },
            )
        ),
    )
    payload = service.watchlist("NIFTY 50")
    assert payload["count"] == 2
    assert payload["rows"][0]["ltp"] == 100
    assert payload["rows"][0]["day_change_rs"] is None
    assert payload["rows"][0]["day_change_pct"] is None


def test_stock_detail_never_serializes_nonfinite_or_missing_prices_as_zero():
    frame = pd.DataFrame(
        [
            {
                "open": 100,
                "high": float("inf"),
                "low": 99,
                "close": 102,
                "volume": float("nan"),
            }
        ],
        index=pd.to_datetime(["2026-10-22"]),
    )
    service = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        provider_factory=SimpleNamespace(
            quote=lambda: SimpleNamespace(
                safe_quote=lambda instruments: {
                    "NSE:TCS": {"last_price": True, "ohlc": {"open": float("nan")}}
                }
            ),
            kite_market_data=lambda: SimpleNamespace(
                candles=lambda *args, **kwargs: frame
            ),
        ),
    )
    payload = service.stock_detail("TCS")
    assert payload["ltp"] is None
    assert payload["ohlc"]["open"] is None
    assert payload["candles"][0]["high"] is None
    assert payload["candles"][0]["volume"] is None
    assert payload["candles"][0]["close"] == 102
    json.dumps(payload, allow_nan=False)
