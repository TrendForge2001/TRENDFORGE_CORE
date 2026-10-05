from __future__ import annotations

import pandas as pd
import pytest

from providers.market_data_adapter import MarketDataAdapter
from providers.market_data_provider import MarketDataProvider
from providers.kite_provider import KiteProvider
from providers.nse_provider import NSEProvider
from providers.yfinance_provider import YahooFinanceProvider


def test_provider_classes_implement_market_data_contract():
    assert issubclass(KiteProvider, MarketDataProvider)
    assert issubclass(NSEProvider, MarketDataProvider)
    assert issubclass(YahooFinanceProvider, MarketDataProvider)


def test_adapter_implements_market_data_contract():
    assert issubclass(MarketDataAdapter, MarketDataProvider)


def test_adapter_normalizes_ohlcv_output(ohlcv_frame):
    class StubProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            return ohlcv_frame.copy()

    result = MarketDataAdapter(StubProvider()).candles("ABC")
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]
    assert len(result) == len(ohlcv_frame)
    assert all(pd.api.types.is_numeric_dtype(result[column]) for column in result.columns)


def test_adapter_normalizes_multiindex_output(multiindex_ohlcv_frame):
    class StubProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            return multiindex_ohlcv_frame.copy()

    result = MarketDataAdapter(StubProvider()).candles("ABC")
    assert list(result.columns) == ["open", "high", "low", "close", "volume"]


def test_adapter_rejects_missing_ohlcv_columns(ohlcv_frame):
    class StubProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            return ohlcv_frame.drop(columns=["volume"])

    with pytest.raises(ValueError, match="incomplete OHLCV"):
        MarketDataAdapter(StubProvider()).candles("ABC")


def test_adapter_rejects_empty_output(empty_ohlcv_frame):
    class StubProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            return empty_ohlcv_frame.copy()

    with pytest.raises(ValueError, match="no candle data"):
        MarketDataAdapter(StubProvider()).candles("ABC")


def test_adapter_rejects_invalid_symbol(ohlcv_frame):
    class StubProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            return ohlcv_frame.copy()

    with pytest.raises(ValueError, match="Symbol is required"):
        MarketDataAdapter(StubProvider()).candles("")


def test_adapter_reports_batch_failures_without_losing_successes(ohlcv_frame):
    class MixedProvider:
        def candles(self, symbol, period="1y", interval="1d"):
            if symbol == "BAD":
                raise RuntimeError("provider failure")
            return ohlcv_frame.copy()

    adapter = MarketDataAdapter(MixedProvider(), max_workers=2)
    results, failures = adapter.batch_candles_with_errors(["GOOD", "BAD", "GOOD"])
    assert set(results) == {"GOOD"}
    assert "BAD" in failures

    repeated = adapter.batch_candles(["GOOD", "BAD"])
    assert set(repeated) == {"GOOD"}
    assert "BAD" in adapter.last_batch_errors


def test_adapter_rejects_provider_without_supported_method():
    adapter = MarketDataAdapter(object())
    with pytest.raises(AttributeError, match="historical_data\(\) or candles\(\)"):
        adapter.candles("ABC")
