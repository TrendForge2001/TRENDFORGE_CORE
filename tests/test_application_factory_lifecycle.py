from __future__ import annotations

from core.application_factory import ApplicationFactory


class ProviderFactorySpy:
    def __init__(self):
        self.market_data_calls = 0
        self.market_data_instance = object()

    def market_data(self):
        self.market_data_calls += 1
        return self.market_data_instance


class DomainFactorySpy:
    def __init__(self):
        self.news_instance = object()
        self.corporate_action_instance = object()

    def news(self):
        return self.news_instance

    def corporate_actions(self):
        return self.corporate_action_instance


def test_market_data_is_cached_per_application_factory():
    providers = ProviderFactorySpy()
    factory = ApplicationFactory(provider_factory=providers)

    assert factory.market_data() is factory.market_data()
    assert providers.market_data_calls == 1


def test_scanner_pipeline_and_service_are_cached_per_application_factory():
    providers = ProviderFactorySpy()
    factory = ApplicationFactory(provider_factory=providers)

    assert factory.scanner_pipeline() is factory.scanner_pipeline()
    assert factory.scanner_service() is factory.scanner_service()
    assert factory.scanner_service().pipeline is factory.scanner_pipeline()


def test_factories_do_not_share_cached_components_across_application_instances():
    first = ApplicationFactory(provider_factory=ProviderFactorySpy())
    second = ApplicationFactory(provider_factory=ProviderFactorySpy())

    assert first.scanner_pipeline() is not second.scanner_pipeline()
    assert first.scanner_service() is not second.scanner_service()
