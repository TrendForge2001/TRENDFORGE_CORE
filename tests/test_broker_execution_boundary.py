"""Exercise broker execution boundaries with an in-memory SDK only."""

from __future__ import annotations

import pytest
import requests
from providers.kite_errors import NetworkException

import api.kite_service as service_module
import config.settings as settings
import providers.kite_provider as provider_module
from core.broker_execution_policy import LiveTradingDisabled


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.failures = {}
        self.result = object()

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.failures.get(name, 0):
            self.failures[name] -= 1
            raise NetworkException("Ambiguous broker network response")
        return self.result

    def place_order(self, *args, **kwargs):
        return self._record("place_order", *args, **kwargs)

    def modify_order(self, *args, **kwargs):
        return self._record("modify_order", *args, **kwargs)

    def cancel_order(self, *args, **kwargs):
        return self._record("cancel_order", *args, **kwargs)

    def quote(self, *args, **kwargs):
        return self._record("quote", *args, **kwargs)

    def ltp(self, *args, **kwargs):
        return self._record("ltp", *args, **kwargs)

    def historical_data(self, *args, **kwargs):
        return self._record("historical_data", *args, **kwargs)

    def profile(self):
        return self._record("profile")

    def margins(self):
        return self._record("margins")

    def holdings(self):
        return self._record("holdings")

    def positions(self):
        return self._record("positions")

    def orders(self):
        return self._record("orders")

    def trades(self):
        return self._record("trades")

    def order_history(self, order_id):
        return self._record("order_history", order_id)

    def login_url(self):
        return self._record("login_url")

    def generate_session(self, *args, **kwargs):
        return self._record("generate_session", *args, **kwargs)

    def set_access_token(self, token):
        return self._record("set_access_token", token)

    def invalidate_access_token(self):
        return self._record("invalidate_access_token")

    def place_gtt(self, *args, **kwargs):
        return self._record("place_gtt", *args, **kwargs)

    modify_gtt = delete_gtt = convert_position = place_gtt
    _post = _put = _delete = _get = _request = place_gtt
    request = session = place_gtt


@pytest.fixture(autouse=True)
def forbid_real_broker_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("These tests must never perform network requests")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)


@pytest.fixture(params=["provider", "service"])
def broker(request):
    fake = FakeBroker()
    if request.param == "provider":
        wrapper = object.__new__(provider_module.KiteProvider)
        wrapper.kite = fake
    else:
        wrapper = object.__new__(service_module.KiteService)
        wrapper._kite = fake
    wrapper.live_trading_enabled = True
    return request.param, wrapper, fake


def public_client(kind, wrapper):
    return wrapper.kite if kind == "provider" else wrapper.client


def write_kwargs(operation):
    if operation == "place_order":
        return {
            "variety": "regular",
            "exchange": "NSE",
            "tradingsymbol": "TCS",
            "transaction_type": "BUY",
            "quantity": 2,
            "product": "CNC",
            "order_type": "LIMIT",
            "price": 100.5,
            "trigger_price": 99.5,
        }
    if operation == "modify_order":
        return {"variety": "regular", "order_id": "ORDER-1", "quantity": 3}
    return {"variety": "regular", "order_id": "ORDER-1"}


def write(kind, wrapper, operation):
    kwargs = write_kwargs(operation)
    if operation == "place_order":
        return wrapper.place_order(**kwargs)
    variety = kwargs.pop("variety")
    order_id = kwargs.pop("order_id")
    if kind == "provider":
        return getattr(wrapper, operation)(variety, order_id, **kwargs)
    return getattr(wrapper, operation)(order_id, variety=variety, **kwargs)


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
@pytest.mark.parametrize("runtime", [None, "false", "invalid"])
def test_all_order_operations_require_current_runtime_opt_in(
    broker, monkeypatch, operation, runtime
):
    kind, wrapper, fake = broker
    if runtime is None:
        monkeypatch.delenv("TRENDFORGE_LIVE_TRADING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", runtime)
    with pytest.raises(LiveTradingDisabled, match="disabled"):
        write(kind, wrapper, operation)
    assert fake.calls == []


@pytest.mark.parametrize("captured", [False, None, "true", 1, "missing"])
def test_current_opt_in_cannot_enable_an_unconsenting_instance(
    broker, monkeypatch, captured
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    if captured == "missing":
        del wrapper.live_trading_enabled
    else:
        wrapper.live_trading_enabled = captured
    with pytest.raises(LiveTradingDisabled):
        write(kind, wrapper, "place_order")
    assert fake.calls == []


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
def test_opted_in_order_operations_forward_once_without_changing_result(
    broker, monkeypatch, operation
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    assert write(kind, wrapper, operation) is fake.result
    assert fake.calls == [(operation, (), write_kwargs(operation))]


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
def test_ambiguous_order_network_failures_are_never_retried(
    broker, monkeypatch, operation
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    fake.failures[operation] = 1
    with pytest.raises(NetworkException):
        write(kind, wrapper, operation)
    assert fake.calls == [(operation, (), write_kwargs(operation))]


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
def test_disabled_disconnected_orders_fail_at_the_policy_boundary(
    broker, monkeypatch, operation
):
    kind, wrapper, _ = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    if kind == "provider":
        del wrapper._kite_client
    else:
        wrapper._kite = None
    with pytest.raises(LiveTradingDisabled):
        write(kind, wrapper, operation)


@pytest.mark.parametrize("operation", ["place_order", "modify_order", "cancel_order"])
@pytest.mark.parametrize("revoke", ["runtime", "instance"])
def test_public_client_and_cached_order_callable_recheck_consent(
    broker, monkeypatch, operation, revoke
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    client = public_client(kind, wrapper)
    assert client is not fake
    cached_order = getattr(client, operation)
    assert cached_order(**write_kwargs(operation)) is fake.result
    fake.calls.clear()
    if revoke == "runtime":
        monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    else:
        wrapper.live_trading_enabled = False
    for call in (cached_order, getattr(client, operation)):
        with pytest.raises(LiveTradingDisabled):
            call(**write_kwargs(operation))
    assert fake.calls == []


@pytest.mark.parametrize(
    "name",
    [
        "place_gtt",
        "modify_gtt",
        "delete_gtt",
        "convert_position",
        "_post",
        "_put",
        "_delete",
        "_get",
        "_request",
        "request",
        "session",
        "unknown_operation",
    ],
)
def test_public_client_rejects_unsupported_and_private_sdk_access(
    broker, monkeypatch, name
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    with pytest.raises(AttributeError):
        getattr(public_client(kind, wrapper), name)()
    assert fake.calls == []


@pytest.mark.parametrize(
    "method,args",
    [
        ("profile", ()),
        ("margins", ()),
        ("holdings", ()),
        ("positions", ()),
        ("orders", ()),
        ("trades", ()),
        ("quote", (["NSE:TCS"],)),
        ("ltp", (["NSE:TCS"],)),
        ("order_history", ("ORDER-1",)),
        ("historical_data", (123, "2026-01-01", "2026-01-31", "day")),
    ],
)
def test_read_operations_remain_available_when_live_orders_are_disabled(
    broker, monkeypatch, method, args
):
    _, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    wrapper.live_trading_enabled = False
    assert getattr(wrapper, method)(*args) is fake.result
    assert len(fake.calls) == 1
    assert fake.calls[0][0] == method


@pytest.mark.parametrize(
    "method,args",
    [
        ("login_url", ()),
        ("generate_session", ("request-token",)),
        ("set_access_token", ("test-token",)),
        ("invalidate_access_token", ()),
    ],
)
def test_session_operations_remain_available_with_live_orders_disabled(
    broker, monkeypatch, method, args
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    assert getattr(public_client(kind, wrapper), method)(*args) is fake.result
    assert fake.calls == [(method, args, {})]


@pytest.mark.parametrize(
    "alias,side,order_type,price",
    [
        ("exit_position", "SELL", "MARKET", None),
        ("buy_market", "BUY", "MARKET", None),
        ("sell_market", "SELL", "MARKET", None),
        ("buy_limit", "BUY", "LIMIT", 100.5),
        ("sell_limit", "SELL", "LIMIT", 100.5),
    ],
)
def test_legacy_aliases_obey_the_same_guard_and_preserve_order_details(
    monkeypatch, alias, side, order_type, price
):
    wrapper = object.__new__(service_module.KiteService)
    wrapper._kite = fake = FakeBroker()
    wrapper.live_trading_enabled = True
    args = ("NSE", "TCS", 2) if price is None else ("NSE", "TCS", 2, price)
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    with pytest.raises(LiveTradingDisabled):
        getattr(wrapper, alias)(*args, product="CNC")
    assert fake.calls == []
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    assert getattr(wrapper, alias)(*args, product="CNC") is fake.result
    assert fake.calls == [
        (
            "place_order",
            (),
            {
                "variety": "regular",
                "exchange": "NSE",
                "tradingsymbol": "TCS",
                "transaction_type": side,
                "quantity": 2,
                "product": "CNC",
                "order_type": order_type,
                "price": price,
                "trigger_price": None,
            },
        )
    ]


@pytest.mark.parametrize("kind", ["provider", "service"])
@pytest.mark.parametrize("captured", [False, True])
def test_real_constructors_capture_the_instance_opt_in(
    monkeypatch, tmp_path, kind, captured
):
    fake = FakeBroker()
    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", captured)
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    monkeypatch.chdir(tmp_path)
    if kind == "provider":
        monkeypatch.setattr(settings, "KITE_ACCESS_TOKEN", None)
        monkeypatch.setattr(provider_module, "KiteConnect", lambda **kwargs: fake)
        wrapper = object.__new__(provider_module.KiteProvider)
        wrapper.__init__()
    else:
        monkeypatch.setattr(service_module, "KITE_ACCESS_TOKEN", None)
        monkeypatch.setattr(service_module, "KiteConnect", lambda **kwargs: fake)
        wrapper = service_module.KiteService()
        assert wrapper._kite is None
        wrapper._kite = fake
    assert wrapper.live_trading_enabled is captured
    monkeypatch.setattr(settings, "LIVE_TRADING_ENABLED", not captured)
    if captured:
        assert write(kind, wrapper, "place_order") is fake.result
        assert len(fake.calls) == 1
    else:
        with pytest.raises(LiveTradingDisabled):
            write(kind, wrapper, "place_order")
        assert fake.calls == []


@pytest.mark.parametrize("method", ["quote", "ltp", "historical_data"])
def test_safe_market_reads_retry_transient_network_failures(
    broker, monkeypatch, method
):
    kind, wrapper, fake = broker
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setattr(provider_module.time, "sleep", lambda seconds: None)
    fake.failures[method] = 2
    if kind == "service":
        result = wrapper.execute(getattr(wrapper.client, method), "read-argument")
    else:
        safe_method = {
            "quote": wrapper.safe_quote,
            "ltp": wrapper.safe_ltp,
            "historical_data": wrapper.safe_historical,
        }[method]
        result = safe_method("read-argument")
    assert result is fake.result
    assert fake.calls == [(method, ("read-argument",), {})] * 3


class PretendQuote:
    __name__ = "quote"

    def __init__(self):
        self.calls = 0

    def __eq__(self, other):
        return True

    def __call__(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Arbitrary callables must not run through broker retries")


@pytest.mark.parametrize(
    "operation",
    ["place_order", "modify_order", "cancel_order", "arbitrary", "other_client"],
)
def test_legacy_execute_rejects_writes_and_impersonated_reads(monkeypatch, operation):
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    wrapper = object.__new__(service_module.KiteService)
    wrapper._kite = fake = FakeBroker()
    wrapper.live_trading_enabled = True
    arbitrary = PretendQuote()
    other = FakeBroker()
    func = (
        arbitrary
        if operation == "arbitrary"
        else other.quote
        if operation == "other_client"
        else getattr(wrapper.client, operation)
    )
    with pytest.raises(ValueError, match="quote, ltp and historical_data only"):
        wrapper.execute(func)
    assert fake.calls == other.calls == []
    assert arbitrary.calls == 0


@pytest.mark.parametrize("retries", [0, 4, True, "3"])
def test_legacy_read_retry_budget_is_bounded(retries):
    wrapper = object.__new__(service_module.KiteService)
    wrapper._kite = fake = FakeBroker()
    with pytest.raises(ValueError, match="between 1 and 3"):
        wrapper.execute(wrapper.client.quote, "NSE:TCS", retries=retries)
    assert fake.calls == []


@pytest.mark.parametrize(
    "method",
    ["place_order", "modify_order", "cancel_order", "_post", "unknown_operation"],
)
def test_provider_retry_helper_rejects_non_market_reads(method):
    wrapper = object.__new__(provider_module.KiteProvider)
    wrapper.kite = fake = FakeBroker()
    with pytest.raises(ValueError, match="market-data reads"):
        wrapper._retry_read(method)
    assert fake.calls == []
