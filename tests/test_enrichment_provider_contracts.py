from __future__ import annotations

from typing import Any

from reconstruction.enrichment_provider_contracts import CorporateActionProvider, NewsProvider


class FakeNewsProvider:
    def news(self, symbol: str):
        return [{"title": f"News for {symbol}"}]


class FakeCorporateActionProvider:
    def corporate_actions(self):
        return [{"subject": "Dividend"}]


def test_news_provider_contract_is_structural():
    provider: NewsProvider = FakeNewsProvider()
    assert provider.news("RELIANCE")


def test_corporate_action_provider_contract_is_structural():
    provider: CorporateActionProvider = FakeCorporateActionProvider()
    assert provider.corporate_actions()


def test_domain_contracts_are_separate_from_market_data_adapter():
    from providers.market_data_adapter import MarketDataAdapter

    assert MarketDataAdapter is not NewsProvider
    assert MarketDataAdapter is not CorporateActionProvider
