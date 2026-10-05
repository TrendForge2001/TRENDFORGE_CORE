from __future__ import annotations

from core.application_factory import ApplicationFactory
from core.domain_provider_factory import DomainProviderFactory
from providers import (
    CompositeNewsProvider,
    NSECorporateActionProvider,
)


def test_application_factory_owns_domain_provider_factory():
    factory = ApplicationFactory()
    assert isinstance(factory.domain_providers, DomainProviderFactory)


def test_application_factory_exposes_canonical_domain_providers():
    factory = ApplicationFactory()
    assert isinstance(factory.news_provider(), CompositeNewsProvider)
    assert isinstance(factory.corporate_action_provider(), NSECorporateActionProvider)


def test_domain_provider_factory_supports_injection():
    news = object()
    actions = object()
    factory = DomainProviderFactory(news_provider=news, corporate_action_provider=actions)
    assert factory.news() is news
    assert factory.corporate_actions() is actions
