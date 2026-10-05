from __future__ import annotations

from providers.domain_provider_contracts import CorporateActionProvider, NewsProvider


def test_news_provider_contract_exists():
    assert NewsProvider is not None
    assert hasattr(NewsProvider, "get_news")


def test_corporate_action_provider_contract_exists():
    assert CorporateActionProvider is not None
    assert hasattr(CorporateActionProvider, "get_corporate_actions")


def test_domain_contracts_remain_separate():
    assert NewsProvider is not CorporateActionProvider
