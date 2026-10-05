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
