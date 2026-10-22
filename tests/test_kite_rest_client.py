"""Kite protocol contracts using fake HTTP responses and no broker connection."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from core.broker_execution_policy import LiveTradingDisabled
from providers.kite_errors import (
    DataException,
    InputException,
    KiteException,
    NetworkException,
    TokenException,
)
from providers.kite_rest_client import KiteRESTClient

BASE = "https://api.kite.trade"


class FakeResponse:
    def __init__(self, payload=None, *, status=200, content=None, content_type=None):
        self.status_code = status
        self.payload = payload
        self.content = json.dumps(payload).encode() if content is None else content
        self.headers = {
            "Content-Type": content_type or "application/json; charset=utf-8"
        }
        self.text = self.content.decode("utf-8", errors="replace")
        self.closed = False

    def json(self):
        return json.loads(self.content)

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unexpected extra broker request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def success(data):
    return FakeResponse({"status": "success", "data": data})


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Transport contracts must not use the network")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


@pytest.fixture
def identity():
    # Generate nonfunctional fixture values rather than embedding credentials.
    return secrets.token_hex(12), secrets.token_hex(18)


def client_for(identity, *responses, execution_guard=None):
    key, token = identity
    session = FakeSession(*responses)
    client = KiteRESTClient(
        api_key=key,
        access_token=token,
        session=session,
        execution_guard=execution_guard,
    )
    return client, session


def assert_request(call, identity, method, path, *, params=None, data=None):
    actual_method, url, options = call
    key, token = identity
    assert (actual_method, url) == (method, BASE + path)
    assert options["headers"]["X-Kite-Version"] == "3"
    assert options["headers"]["Authorization"] == f"token {key}:{token}"
    assert options["allow_redirects"] is False
    assert 0 < options["timeout"] <= 60
    assert options.get("params") == params
    assert options.get("data") == data


def test_constructor_is_offline_and_missing_auth_cannot_make_a_request():
    session = FakeSession()
    client = KiteRESTClient(session=session)
    assert session.calls == []
    with pytest.raises(TokenException):
        client.profile()
    assert session.calls == []


@pytest.mark.parametrize(
    "adapter_prefix", [BASE + "/", BASE + "/orders/", BASE.upper() + "/orders/"]
)
def test_injected_requests_session_cannot_enable_tls_bypass_or_order_retries(
    identity, adapter_prefix
):
    session = requests.Session()
    session.verify = False
    session.mount(adapter_prefix, requests.adapters.HTTPAdapter(max_retries=3))
    assert session.get_adapter(BASE + "/orders/regular").max_retries.total == 3
    KiteRESTClient(api_key=identity[0], access_token=identity[1], session=session)
    assert session.verify is True
    assert session.get_adapter(BASE + "/orders/regular").max_retries.total == 0


def test_login_url_encodes_the_public_key_without_an_access_token():
    key = "key with & reserved?characters"
    client = KiteRESTClient(api_key=key)
    parsed = urlsplit(client.login_url())
    assert (parsed.scheme, parsed.netloc, parsed.path) == (
        "https",
        "kite.zerodha.com",
        "/connect/login",
    )
    assert parse_qs(parsed.query) == {"api_key": [key], "v": ["3"]}


def test_exchange_uses_the_checksum_and_installs_the_returned_session(identity):
    key, old_token = identity
    request_token, api_secret, new_token = (secrets.token_hex(16) for _ in range(3))
    client, session = client_for(
        identity,
        success({"access_token": new_token, "login_time": "2026-10-22 09:00:00"}),
        success({"user_id": "fixture-user"}),
    )
    result = client.generate_session(request_token, api_secret=api_secret)
    assert result["access_token"] == new_token
    assert result["login_time"] == datetime(2026, 10, 22, 9)
    checksum = hashlib.sha256((key + request_token + api_secret).encode()).hexdigest()
    method, url, options = session.calls[0]
    assert (method, url) == ("POST", BASE + "/session/token")
    assert options.get("data") == {
        "api_key": key,
        "request_token": request_token,
        "checksum": checksum,
    }
    assert options["allow_redirects"] is False
    assert api_secret not in json.dumps(session.calls)
    assert client.access_token == new_token != old_token
    assert client.profile() == {"user_id": "fixture-user"}
    assert_request(session.calls[1], (key, new_token), "GET", "/user/profile")


@pytest.mark.parametrize("failed", [False, True])
def test_logout_uses_current_token_and_clears_it_even_on_failure(identity, failed):
    response = (
        requests.Timeout("synthetic transport failure") if failed else success({})
    )
    client, session = client_for(identity, response)
    if failed:
        with pytest.raises(NetworkException):
            client.invalidate_access_token()
    else:
        assert client.invalidate_access_token() == {}
    assert client.access_token is None
    assert_request(
        session.calls[0],
        identity,
        "DELETE",
        "/session/token",
        params={"api_key": identity[0], "access_token": identity[1]},
    )
    with pytest.raises(TokenException):
        client.profile()
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "method,args,path,payload",
    [
        ("profile", (), "/user/profile", {"user_id": "fixture-user"}),
        ("margins", (), "/user/margins", {"equity": {"net": 100}}),
        ("margins", ("equity",), "/user/margins/equity", {"net": 100}),
        ("holdings", (), "/portfolio/holdings", [{"tradingsymbol": "TCS"}]),
        ("positions", (), "/portfolio/positions", {"net": [], "day": []}),
        ("orders", (), "/orders", [{"order_id": "ORDER-1"}]),
        ("trades", (), "/trades", [{"trade_id": "TRADE-1"}]),
        ("order_history", ("ORDER-1",), "/orders/ORDER-1", []),
        ("order_trades", ("ORDER-1",), "/orders/ORDER-1/trades", []),
        ("get_gtts", (), "/gtt/triggers", []),
    ],
)
def test_account_and_order_reads_preserve_routes_and_response_shapes(
    identity, method, args, path, payload
):
    client, session = client_for(identity, success(payload))
    assert getattr(client, method)(*args) == payload
    assert len(session.calls) == 1
    assert_request(session.calls[0], identity, "GET", path)


@pytest.mark.parametrize(
    "method,path", [("quote", "/quote"), ("ohlc", "/quote/ohlc"), ("ltp", "/quote/ltp")]
)
@pytest.mark.parametrize("style", ["string", "list", "variadic"])
def test_quote_inputs_become_repeated_i_query_parameters(identity, method, path, style):
    instruments = ["NSE:TCS", "NSE:M&M"]
    args = {
        "string": (instruments[0],),
        "list": (instruments,),
        "variadic": tuple(instruments),
    }[style]
    requested = instruments[:1] if style == "string" else instruments
    payload = {symbol: {"last_price": 100.0} for symbol in requested}
    client, session = client_for(identity, success(payload))
    assert getattr(client, method)(*args) == payload
    assert_request(session.calls[0], identity, "GET", path, params={"i": requested})


@pytest.mark.parametrize(
    "method,args",
    [
        ("orders", ()),
        ("trades", ()),
        ("order_history", ("ORDER-1",)),
        ("order_trades", ("ORDER-1",)),
        ("quote", ("NSE:TCS",)),
    ],
)
def test_order_and_quote_datetime_fields_keep_the_legacy_normalization(
    identity, method, args
):
    fields = (
        "order_timestamp",
        "exchange_timestamp",
        "created",
        "last_instalment",
        "fill_timestamp",
        "timestamp",
        "last_trade_time",
    )
    item = {field: "2026-10-22 09:15:00" for field in fields}
    item["untouched"] = "2026-10-22"
    data = {"NSE:TCS": item} if method == "quote" else [item]
    client, _ = client_for(identity, success(data))
    result = getattr(client, method)(*args)
    normalized = result["NSE:TCS"] if method == "quote" else result[0]
    for field in fields:
        assert normalized[field] == datetime(2026, 10, 22, 9, 15)
    assert normalized["untouched"] == "2026-10-22"


@pytest.mark.parametrize(
    "exchange,path", [(None, "/instruments"), ("NFO", "/instruments/NFO")]
)
def test_instrument_csv_preserves_typed_columns_and_empty_expiry(
    identity, exchange, path
):
    csv = (
        b"instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,"
        b"strike,tick_size,lot_size,instrument_type,segment,exchange\n"
        b'123,456,TCS,"Example, Limited",100.5,,0,0.05,1,EQ,NSE,NSE\n'
        b"789,987,TCSFUT,Future,110,2026-10-29,100,0.05,150,FUT,NFO-FUT,NFO\n"
    )
    client, session = client_for(
        identity, FakeResponse(content=csv, content_type="text/csv")
    )
    rows = client.instruments(exchange) if exchange else client.instruments()
    assert_request(session.calls[0], identity, "GET", path)
    assert rows[0] == {
        "instrument_token": 123,
        "exchange_token": "456",
        "tradingsymbol": "TCS",
        "name": "Example, Limited",
        "last_price": 100.5,
        "expiry": "",
        "strike": 0.0,
        "tick_size": 0.05,
        "lot_size": 1,
        "instrument_type": "EQ",
        "segment": "NSE",
        "exchange": "NSE",
    }
    assert rows[1]["expiry"] == date(2026, 10, 29)
    assert rows[1]["lot_size"] == 150


@pytest.mark.parametrize("with_oi", [False, True])
def test_candles_preserve_offset_dates_ohlcv_and_optional_open_interest(
    identity, with_oi
):
    candle = ["2026-10-22T09:15:00+0530", 100, 103, 99, 102, 1200]
    if with_oi:
        candle.append(17)
    client, session = client_for(identity, success({"candles": [candle]}))
    start = datetime(
        2026, 10, 22, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    result = client.historical_data(
        123, start, "2026-10-22 15:30:00", "5minute", True, with_oi
    )
    expected = {
        "date": start,
        "open": 100,
        "high": 103,
        "low": 99,
        "close": 102,
        "volume": 1200,
    }
    if with_oi:
        expected["oi"] = 17
    assert result == [expected]
    assert result[0]["date"].utcoffset() == timedelta(hours=5, minutes=30)
    assert_request(
        session.calls[0],
        identity,
        "GET",
        "/instruments/historical/123/5minute",
        params={
            "from": "2026-10-22 09:15:00",
            "to": "2026-10-22 15:30:00",
            "interval": "5minute",
            "continuous": 1,
            "oi": int(with_oi),
        },
    )


@pytest.mark.parametrize("operation", ["place", "modify", "cancel"])
def test_mutations_deny_before_auth_or_network_without_an_execution_guard(operation):
    client = KiteRESTClient(session=FakeSession())
    with pytest.raises(LiveTradingDisabled):
        invoke_write(client, operation)


def invoke_write(client, operation):
    if operation == "place":
        return client.place_order(
            "regular",
            "NSE",
            "TCS",
            "BUY",
            2,
            "CNC",
            "LIMIT",
            price=100.5,
            trigger_price=None,
            tag="fixture",
        )
    if operation == "modify":
        return client.modify_order("regular", "ORDER-1", quantity=3, price=None)
    return client.cancel_order("regular", "ORDER-1", parent_order_id="PARENT-1")


@pytest.mark.parametrize(
    "operation,method,path,data,params",
    [
        (
            "place",
            "POST",
            "/orders/regular",
            {
                "variety": "regular",
                "exchange": "NSE",
                "tradingsymbol": "TCS",
                "transaction_type": "BUY",
                "quantity": 2,
                "product": "CNC",
                "order_type": "LIMIT",
                "price": 100.5,
                "tag": "fixture",
            },
            None,
        ),
        (
            "modify",
            "PUT",
            "/orders/regular/ORDER-1",
            {"variety": "regular", "order_id": "ORDER-1", "quantity": 3},
            None,
        ),
        (
            "cancel",
            "DELETE",
            "/orders/regular/ORDER-1",
            None,
            {"parent_order_id": "PARENT-1"},
        ),
    ],
)
def test_explicitly_guarded_mutations_forward_once_and_return_only_order_id(
    identity, operation, method, path, data, params
):
    checks = []
    client, session = client_for(
        identity,
        success({"order_id": "ORDER-1"}),
        execution_guard=lambda: checks.append("checked"),
    )
    assert invoke_write(client, operation) == "ORDER-1"
    assert checks == ["checked"]
    assert len(session.calls) == 1
    assert_request(session.calls[0], identity, method, path, data=data, params=params)


@pytest.mark.parametrize("operation", ["place", "modify", "cancel"])
def test_guard_rejection_and_ambiguous_network_errors_cannot_repeat_orders(
    identity, operation
):
    def deny():
        raise LiveTradingDisabled("Live trading disabled")

    # A disabled write must fail before credential validation too.
    denied, session = client_for(("", ""), execution_guard=deny)
    with pytest.raises(LiveTradingDisabled):
        invoke_write(denied, operation)
    assert session.calls == []
    client, session = client_for(
        identity, requests.Timeout("Ambiguous acceptance"), execution_guard=lambda: None
    )
    with pytest.raises(NetworkException):
        invoke_write(client, operation)
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "status,remote_type,error",
    [
        (403, "TokenException", TokenException),
        (400, "InputException", InputException),
        (503, "NetworkException", NetworkException),
        (502, "DataException", DataException),
        (500, "UnrecognizedRemoteException", KiteException),
    ],
)
def test_remote_errors_keep_safe_exception_types_and_http_codes(
    identity, status, remote_type, error
):
    secret = " / ".join(identity)
    client, session = client_for(
        identity,
        FakeResponse(
            {"status": "error", "error_type": remote_type, "message": secret},
            status=status,
        ),
    )
    with pytest.raises(error) as caught:
        client.profile()
    assert caught.value.code == status
    assert all(value not in str(caught.value) for value in identity)
    assert len(session.calls) == 1


def test_transport_exception_text_never_exposes_the_session_credentials(identity):
    client, session = client_for(identity, requests.ConnectionError(" ".join(identity)))
    with pytest.raises(NetworkException) as caught:
        client.profile()
    assert caught.value.code == 503
    assert all(value not in str(caught.value) for value in identity)
    assert caught.value.__cause__ is None
    assert len(session.calls) == 1


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirects_cannot_forward_broker_credentials(identity, status):
    client, session = client_for(identity, FakeResponse(status=status))
    with pytest.raises(KiteException):
        client.profile()
    assert session.calls[0][2]["allow_redirects"] is False
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(
            content=b"<html>untrusted gateway</html>", content_type="text/html"
        ),
        FakeResponse(content=b"not JSON"),
        FakeResponse([]),
        FakeResponse({"status": "success"}),
        FakeResponse({"status": "success", "data": {"price": float("nan")}}),
        FakeResponse({"status": "success", "data": {"price": float("inf")}}),
        FakeResponse(
            {"status": "success", "data": {"nested": [{"price": float("nan")}]}}
        ),
    ],
)
def test_invalid_response_shapes_and_nonfinite_numbers_fail_safely(identity, response):
    client, session = client_for(identity, response)
    with pytest.raises(DataException):
        client.profile()
    assert len(session.calls) == 1


@pytest.mark.parametrize("remote_type", [{"untrusted": "value"}, ["TokenException"]])
def test_malformed_error_type_is_rejected_without_dictionary_lookup_failures(
    identity, remote_type
):
    client, session = client_for(
        identity,
        FakeResponse(
            {
                "status": "error",
                "error_type": remote_type,
                "message": " ".join(identity),
            },
            status=400,
        ),
    )
    with pytest.raises(DataException) as caught:
        client.profile()
    assert all(value not in str(caught.value) for value in identity)
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"candles": [["not-a-date", 1, 2, 0, 1, 10]]},
        {"candles": [["2026-10-22T09:15:00+0530", 1, 2]]},
        {"candles": [["2026-10-22T09:15:00+0530", 1, "invalid", 0, 1, 10]]},
    ],
)
def test_malformed_candles_are_rejected_instead_of_becoming_market_data(
    identity, payload
):
    client, _ = client_for(identity, success(payload))
    with pytest.raises(DataException):
        client.historical_data(123, "2026-10-22", "2026-10-23", "day")


@pytest.mark.parametrize(
    "csv",
    [
        b"instrument_token,tradingsymbol\n123,TCS\n",
        b"instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\ninvalid,456,TCS,TCS,1,,0,0.05,1,EQ,NSE,NSE\n",
    ],
)
def test_malformed_instrument_csv_is_rejected(identity, csv):
    client, _ = client_for(identity, FakeResponse(content=csv, content_type="text/csv"))
    with pytest.raises(DataException):
        client.instruments("NSE")


@pytest.mark.parametrize(
    "method,args",
    [
        ("order_history", ("../user/profile",)),
        ("order_trades", ("ORDER?access_token=other",)),
        ("instruments", ("//outside.example",)),
        ("margins", ("../../session/token",)),
        ("historical_data", (123, "2026-10-22", "2026-10-23", "../quote")),
    ],
)
def test_route_components_cannot_escape_the_selected_kite_endpoint(
    identity, method, args
):
    client, session = client_for(identity)
    with pytest.raises((InputException, ValueError)):
        getattr(client, method)(*args)
    assert session.calls == []
