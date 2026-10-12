from __future__ import annotations

import pandas as pd
import pytest

from providers.market_data_adapter import MarketDataAdapter
from providers.kite_provider import KiteProvider
from providers.nse_provider import NSEProvider
from providers.yfinance_provider import YahooFinanceProvider


class StubProvider:
    def __init__(self, frame=None):
        self.frame = frame if frame is not None else pd.DataFrame({
            "Open": [100.0], "High": [102.0], "Low": [99.0],
            "Close": [101.0], "Volume": [1000],
        })

    def historical_data(self, symbol, period="1y", interval="1d", auto_adjust=False):
        return self.frame


def test_adapter_normalizes_provider_output_to_canonical_ohlcv():
    frame = MarketDataAdapter(StubProvider()).candles("abc")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert frame.iloc[-1]["close"] == 101.0


def test_adapter_rejects_incomplete_provider_contract():
    provider = StubProvider(pd.DataFrame({"close": [101.0]}))
    with pytest.raises(ValueError, match="incomplete OHLCV"):
        MarketDataAdapter(provider).candles("ABC")


def test_adapter_deduplicates_batch_symbols_and_reports_failures():
    class FailingProvider(StubProvider):
        def historical_data(self, symbol, **kwargs):
            if symbol == "BAD":
                raise RuntimeError("provider failure")
            return super().historical_data(symbol, **kwargs)

    adapter = MarketDataAdapter(FailingProvider())
    results, failures = adapter.batch_candles_with_errors(["abc", "ABC", "bad"])
    assert list(results) == ["ABC"]
    assert "BAD" in failures


def test_provider_classes_exist_as_data_source_boundaries():
    assert issubclass(KiteProvider, object)
    assert issubclass(NSEProvider, object)
    assert issubclass(YahooFinanceProvider, object)


def test_yfinance_symbol_normalization_is_provider_local():
    assert YahooFinanceProvider.normalize_symbol("RELIANCE") == "RELIANCE.NS"
    assert YahooFinanceProvider.normalize_symbol("^NSEI") == "^NSEI"


def test_kite_candles_resolve_instrument_and_return_ohlcv(monkeypatch):
    from datetime import datetime, timezone

    provider = object.__new__(KiteProvider)
    provider.api_key = "key"
    provider.api_secret = "secret"
    provider.access_token = "token"
    provider.live_trading_enabled = False
    provider._instrument_token_cache = {"BAGMANE": 12345}
    provider._instrument_cache_loaded = True
    provider._history_lock = __import__("threading").Lock()
    provider._last_history_call_at = 0.0

    calls = []

    def fake_history(token, from_date, to_date, interval, continuous=False, oi=False):
        calls.append((token, interval, continuous, oi))
        return [
            {
                "date": datetime(2026, 10, 10, tzinfo=timezone.utc),
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 5000,
            }
        ]

    monkeypatch.setattr(provider, "safe_historical", fake_history)
    monkeypatch.setattr(provider, "_pace_history", lambda: None)

    frame = provider.candles("BAGMANE", period="6mo", interval="1d")

    assert calls == [(12345, "day", False, False)]
    assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert float(frame.iloc[-1]["Close"]) == 101.0


def test_kite_symbol_alias_resolves_rr_series():
    provider = object.__new__(KiteProvider)
    provider._instrument_token_cache = {"BAGMANERR": 98765}
    provider._instrument_cache_loaded = True
    provider.symbol_aliases = {}
    provider.set_symbol_aliases({"BAGMANE": "BAGMANERR"})

    assert provider.instrument_token_for_symbol("BAGMANE") == 98765


def test_kite_batch_uses_bounded_concurrency(monkeypatch):
    import threading
    import time

    provider = object.__new__(KiteProvider)
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_candles(symbol, period="6mo", interval="1d"):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return pd.DataFrame({
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [100],
        })

    monkeypatch.setattr(provider, "candles", fake_candles)

    results, failures = provider.batch_candles_with_errors(
        [f"S{i}" for i in range(8)],
        period="6mo",
        interval="1d",
    )

    assert failures == {}
    assert len(results) == 8
    assert 1 < max_active <= 3
