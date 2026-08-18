from __future__ import annotations

import pandas as pd
import pytest

from providers.market_data_adapter import MarketDataAdapter
from providers.market_data_provider import MarketDataProvider
from providers.kite_provider import KiteProvider
from providers.nse_provider import NSEProvider
from providers.yfinance_provider import YahooFinanceProvider


class StubProvider:
    def __init__(self, frame=None, error=None):
        self.frame = frame
        self.error = error

    def candles(self, symbol, period="1y", interval="1d"):
        if self.error:
            raise self.error
        return self.frame.copy()


def ohlcv_frame():
    return pd.DataFrame({
        "open": [99, 100], "high": [101, 102], "low": [98, 99],
        "close": [100, 101], "volume": [1000, 1200],
    })


def test_provider_classes_implement_market_data_contract():
    assert issubclass(KiteProvider, MarketDataProvider)
    assert issubclass(NSEProvider, MarketDataProvider)
    assert issubclass(YahooFinanceProvider, MarketDataProvider)


def test_adapter_implements_market_data_contract():
    assert issubclass(MarketDataAdapter, MarketDataProvider)


def test_adapter_normalizes_ohlcv_output():
    adapter = MarketDataAdapter(StubProvider(ohlcv_frame()))
    result = adapter.candles("ABC")
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]
    assert len(result) == 2
    assert all(pd.api.types.is_numeric_dtype(result[column]) for column in result.columns)


def test_adapter_rejects_missing_ohlcv_columns():
    frame = ohlcv_frame().drop(columns=["volume"])
    adapter = MarketDataAdapter(StubProvider(frame))
    with pytest.raises(ValueError, match="incomplete OHLCV"):
        adapter.candles("ABC")


def test_adapter_rejects_empty_output():
    adapter = MarketDataAdapter(StubProvider(pd.DataFrame()))
    with pytest.raises(ValueError, match="no candle data"):
        adapter.candles("ABC")


def test_adapter_rejects_invalid_symbol():
    adapter = MarketDataAdapter(StubProvider(ohlcv_frame()))
    with pytest.raises(ValueError, match="Symbol is required"):
        adapter.candles("")


def test_adapter_reports_batch_failures_without_losing_successes():
    class MixedProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            if symbol == "BAD":
                raise RuntimeError("provider failure")
            return ohlcv_frame()

    adapter = MarketDataAdapter(MixedProvider(), max_workers=2)
    results, failures = adapter.batch_candles_with_errors(["GOOD", "BAD", "GOOD"])
    assert set(results) == {"GOOD"}
    assert "BAD" in failures
    assert adapter.batch_candles(["GOOD", "BAD"]) == results
    assert "BAD" in adapter.last_batch_errors


def test_adapter_rejects_provider_without_supported_method():
    adapter = MarketDataAdapter(object())
    with pytest.raises(AttributeError, match="historical_data.*candles"):
        adapter.candles("ABC")
