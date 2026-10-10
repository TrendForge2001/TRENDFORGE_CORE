from __future__ import annotations

import pandas as pd

from api.scanner_service import ScannerService
from core.application_factory import ApplicationFactory
from providers.market_data_adapter import MarketDataAdapter


class ConfiguredMarketProvider:
    def health(self):
        return {"status": "configured"}

    def candles(self, symbol, period="1y", interval="1d"):
        return pd.DataFrame(
            {
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000.0],
            }
        )


class ProviderFactory:
    runtime_config = None

    def __init__(self):
        self.adapter = MarketDataAdapter(ConfiguredMarketProvider())

    def market_data(self):
        return self.adapter


class DomainProviders:
    def news(self):
        return object()

    def corporate_actions(self):
        return object()


class ConfiguredOrchestrator:
    def health(self):
        return {
            "status": "configured",
            "engine_count": 8,
        }


class RuntimePipeline:
    def __init__(self):
        self.orchestrator = ConfiguredOrchestrator()

    def analyze(self, symbol, **kwargs):
        return {
            "symbol": symbol,
            "signal": "HOLD",
            "passed": False,
        }

    def analyze_many(self, symbols, **kwargs):
        return {
            "results": [],
            "rejected": [
                {
                    "symbol": str(symbols[0]).upper(),
                    "signal": "HOLD",
                    "eligible": False,
                }
            ],
            "scanned_count": 1,
            "rejected_count": 1,
        }


def test_application_health_transitions_after_real_runtime_execution(
    monkeypatch,
):
    monkeypatch.setattr(
        "core.application_factory.database_health",
        lambda: {"status": "ready"},
    )
    monkeypatch.setattr(
        "core.application_factory.runtime_configuration_health",
        lambda _: {"status": "configured"},
    )

    providers = ProviderFactory()
    scanner = ScannerService(RuntimePipeline())
    factory = ApplicationFactory(
        provider_factory=providers,
        domain_provider_factory=DomainProviders(),
        enricher=object(),
    )
    factory._scanner_service = scanner

    before = factory.health()
    assert before["market_data"]["status"] == "configured"
    assert before["scanner"]["status"] == "configured"
    assert before["status"] == "degraded"

    providers.adapter.candles("ABC")
    scanner.scan_many(["ABC"])

    after = factory.health()
    assert after["market_data"]["status"] == "healthy"
    assert after["market_data"]["runtime_status"] == "runtime_verified"
    assert after["scanner"]["status"] == "healthy"
    assert after["scanner"]["runtime_status"] == "runtime_verified"
    assert after["status"] == "healthy"
