"""Safety contract for live Kite order execution."""
import pytest
from providers.kite_provider import KiteProvider


def test_live_order_execution_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_LIVE_TRADING_ENABLED", raising=False)
    provider = object.__new__(KiteProvider)
    provider.live_trading_enabled = False
    class FakeKite:
        def place_order(self, **kwargs):
            raise AssertionError("broker order must not be reached")
    provider.kite = FakeKite()
    with pytest.raises(RuntimeError, match="disabled"):
        provider.place_order(exchange="NSE", tradingsymbol="TCS", transaction_type="BUY", quantity=1)


def test_live_order_execution_can_be_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    provider = object.__new__(KiteProvider)
    provider.live_trading_enabled = True
    class FakeKite:
        def place_order(self, **kwargs):
            return "ORDER-1"
    provider.kite = FakeKite()
    assert provider.place_order(exchange="NSE", tradingsymbol="TCS", transaction_type="BUY", quantity=1) == "ORDER-1"
