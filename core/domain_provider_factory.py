"""Canonical construction of domain-specific non-market-data providers."""
from __future__ import annotations

from providers import (
    CompositeNewsProvider,
    CorporateActionProvider,
    NewsProvider,
    NSECorporateActionProvider,
)


class DomainProviderFactory:
    """Owns construction/injection of news and corporate-action providers."""

    def __init__(
        self,
        news_provider: NewsProvider | None = None,
        corporate_action_provider: CorporateActionProvider | None = None,
    ) -> None:
        self._news_provider = news_provider or CompositeNewsProvider()
        self._corporate_action_provider = (
            corporate_action_provider or NSECorporateActionProvider()
        )

    def news(self) -> NewsProvider:
        return self._news_provider

    def corporate_actions(self) -> CorporateActionProvider:
        return self._corporate_action_provider


__all__ = ["DomainProviderFactory"]
