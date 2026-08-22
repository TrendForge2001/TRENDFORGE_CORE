from __future__ import annotations

from providers import (
    CompositeNewsProvider,
    CorporateActionProvider,
    NSECorporateActionProvider,
    NewsProvider,
)
from services.news_service import NewsService
from services.corporate_action_service import CorporateActionService


class StubNewsProvider(NewsProvider):
    def news(self, symbol: str):
        return [{"title": f"News for {symbol}", "publisher": "stub", "link": ""}]


class StubCorporateProvider(CorporateActionProvider):
    def corporate_actions(self):
        return [{"subject": "DIVIDEND", "purpose": "Dividend", "date": "2026-08-20"}]


def test_news_service_accepts_domain_provider_injection():
    service = NewsService(provider=StubNewsProvider())
    result = service.get_news("ABC")
    assert result and result[0]["title"] == "News for ABC"


def test_corporate_action_service_accepts_domain_provider_injection():
    service = CorporateActionService(provider=StubCorporateProvider())
    result = service.get_actions("ABC")
    assert result and result[0]["symbol"] == "ABC"


def test_concrete_adapters_implement_domain_contracts():
    assert isinstance(CompositeNewsProvider(), NewsProvider)
    assert isinstance(NSECorporateActionProvider(), CorporateActionProvider)
