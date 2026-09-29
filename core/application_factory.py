"""Canonical application construction for TrendForge."""
from __future__ import annotations

from typing import Any


class ApplicationFactory:
    """Build and cache application-scoped components.

    Imports of concrete services/providers are deliberately lazy so importing
    the composition root never initializes external clients or the full engine
    graph during test collection or ASGI module discovery.
    """

    def __init__(
        self,
        provider_factory: Any | None = None,
        domain_provider_factory: Any | None = None,
        enricher: Any | None = None,
        enrichment_providers: dict[str, Any] | None = None,
        **provider_kwargs: Any,
    ) -> None:
        from providers.provider_factory import ProviderFactory
        self.providers = provider_factory or ProviderFactory(**provider_kwargs)

        if domain_provider_factory is None:
            from core.domain_provider_factory import DomainProviderFactory
            domain_provider_factory = DomainProviderFactory()
        self.domain_providers = domain_provider_factory

        if enricher is None and enrichment_providers:
            from reconstruction.enrichment import StockEnricher
            enricher = StockEnricher(enrichment_providers)
        self.enricher = enricher

        self._market_data = None
        self._scanner_pipeline = None
        self._scanner_service = None
        self._news_service = None
        self._corporate_action_service = None

    def market_data(self):
        if self._market_data is None:
            self._market_data = self.providers.market_data()
        return self._market_data

    def news_provider(self):
        return self.domain_providers.news()

    def corporate_action_provider(self):
        return self.domain_providers.corporate_actions()

    def scanner_pipeline(self):
        if self._scanner_pipeline is None:
            from scanner.full_pipeline import FullScannerPipeline
            self._scanner_pipeline = FullScannerPipeline(
                provider=self.market_data(), enricher=self.enricher
            )
        return self._scanner_pipeline

    def scanner_service(self):
        if self._scanner_service is None:
            from api.scanner_service import ScannerService
            self._scanner_service = ScannerService(self.scanner_pipeline())
        return self._scanner_service

    def news_service(self):
        if self._news_service is None:
            from services.news_service import NewsService
            self._news_service = NewsService(provider=self.news_provider())
        return self._news_service

    def corporate_action_service(self):
        if self._corporate_action_service is None:
            from services.corporate_action_service import CorporateActionService
            self._corporate_action_service = CorporateActionService(
                provider=self.corporate_action_provider()
            )
        return self._corporate_action_service

    def health(self) -> dict[str, Any]:
        service = self.scanner_service()
        market = self.market_data()
        market_health = market.health() if callable(getattr(market, "health", None)) else {"status": "unknown"}
        enricher_health = (
            self.enricher.health()
            if self.enricher is not None and callable(getattr(self.enricher, "health", None))
            else {"status": "not_configured"}
        )
        return {
            "status": "healthy",
            "market_data": market_health,
            "enrichment": enricher_health,
            "scanner": service.health(),
            "domain_providers": {
                "news": type(self.news_provider()).__name__,
                "corporate_actions": type(self.corporate_action_provider()).__name__,
            },
        }


__all__ = ["ApplicationFactory"]
