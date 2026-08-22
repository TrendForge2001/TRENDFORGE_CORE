from __future__ import annotations

from core.application_factory import ApplicationFactory
from core.domain_provider_factory import DomainProviderFactory
from providers import CorporateActionProvider, NewsProvider


class FakeNewsProvider(NewsProvider):
    def news(self, symbol: str):
        return [{"title": f"news:{symbol}"}]


class FakeCorporateActionProvider(CorporateActionProvider):
    def corporate_actions(self):
        return [{"subject": "DIVIDEND", "purpose": "test", "date": "2026-08-22"}]


def test_application_factory_composes_domain_services_from_domain_provider_factory():
    domain_factory = DomainProviderFactory(
        news_provider=FakeNewsProvider(),
        corporate_action_provider=FakeCorporateActionProvider(),
    )
    app = ApplicationFactory(domain_provider_factory=domain_factory)

    assert app.news_service().get_news("ABC")[0]["title"] == "news:ABC"
    assert app.corporate_action_service().get_actions("ABC") == []


def test_application_factory_exposes_canonical_domain_provider_types():
    app = ApplicationFactory()
    assert isinstance(app.news_provider(), NewsProvider)
    assert isinstance(app.corporate_action_provider(), CorporateActionProvider)
