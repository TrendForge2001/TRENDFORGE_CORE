from __future__ import annotations

import pandas as pd

from core.application_factory import ApplicationFactory
from providers.market_data_adapter import MarketDataAdapter


class FakeRawProvider:
    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame({
            "Open": [99, 100],
            "High": [101, 102],
            "Low": [98, 99],
            "Close": [100, 101],
            "Volume": [1000, 1200],
        })

    def health(self):
        return {"status": "healthy"}


class FakeProviderFactory:
    def __init__(self):
        self.raw = FakeRawProvider()
        self.adapter = MarketDataAdapter(self.raw)
        self.calls = 0

    def market_data(self):
        self.calls += 1
        return self.adapter


class FakeOrchestrator:
    def evaluate(self, stock):
        assert stock["symbol"] == "ABC"
        assert isinstance(stock["df"], pd.DataFrame)
        assert list(stock["df"].columns) == ["open", "high", "low", "close", "volume"]
        return {
            "passed": True,
            "score": 80,
            "max_score": 100,
            "confidence": 80,
            "signal": "BUY",
            "engines": {},
        }

    def health(self):
        return {"status": "healthy"}


def test_application_factory_to_scanner_service_preserves_canonical_chain(monkeypatch):
    import scanner.full_pipeline as full_pipeline_module

    monkeypatch.setattr(full_pipeline_module, "EngineOrchestrator", FakeOrchestrator)
    providers = FakeProviderFactory()
    app = ApplicationFactory(provider_factory=providers)

    result = app.scanner_service().scan("abc")

    assert result["symbol"] == "ABC"
    assert result["passed"] is True
    assert result["signal"] == "BUY"
    assert result["score"] == 80
    assert providers.calls == 1


def test_application_factory_does_not_construct_raw_market_provider_for_scanner():
    providers = FakeProviderFactory()
    app = ApplicationFactory(provider_factory=providers)
    pipeline = app.scanner_pipeline()

    assert pipeline.provider is providers.adapter
    assert isinstance(pipeline.provider, MarketDataAdapter)
