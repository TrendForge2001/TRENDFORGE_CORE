"""Provider and market-data integration contracts."""

import pandas as pd
import pytest

from providers.market_data_adapter import MarketDataAdapter
from providers.provider_factory import ProviderFactory
from providers.yfinance_provider import YFinanceProvider


class CandlesProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame({
            "Open": [1, 2], "High": [2, 3], "Low": [0.5, 1.5],
            "Close": [1.5, 2.5], "Volume": [100, 200],
        })


def test_adapter_normalizes_provider_ohlcv():
    frame = MarketDataAdapter(CandlesProvider()).candles("test")
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 2


def test_factory_fallback_order():
    yahoo = object()
    nse = object()
    factory = ProviderFactory(kite=None, yahoo=yahoo, nse=nse)
    assert factory.market_data() is yahoo
    assert factory.quote() is nse


def test_factory_rejects_missing_providers():
    with pytest.raises(RuntimeError):
        ProviderFactory().market_data()


def test_yfinance_symbol_normalization():
    assert YFinanceProvider.normalize_symbol("reliance") == "RELIANCE.NS"
    assert YFinanceProvider.normalize_symbol("^NSEI") == "^NSEI"
    assert YFinanceProvider.normalize_symbol("abc.bo") == "ABC.BO"
