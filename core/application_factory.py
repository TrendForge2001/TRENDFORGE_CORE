"""Canonical application construction for TrendForge."""
from __future__ import annotations

from typing import Any

from api.scanner_service import ScannerService
from providers.provider_factory import ProviderFactory
from scanner.full_pipeline import FullScannerPipeline
from reconstruction.enrichment import StockEnricher
from core.domain_provider_factory import DomainProviderFactory
from services.news_service import NewsService
from services.corporate_action_service import CorporateActionService


class ApplicationFactory:
    """Build the application from canonical market and domain providers."""

    def __init__(
        self,
        provider_factory: ProviderFactory | None = None,
        domain_provider_factory: DomainProviderFactory | None = None,
        enricher: StockEnricher | None = None,
        enrichment_providers: dict[str, Any] | None = None,
        **provider_kwargs: Any,
    ):
        self.providers = provider_factory or ProviderFactory(**provider_kwargs)
        self.domain_providers = domain_provider_factory or DomainProviderFactory()
        self.enricher = enricher or (
            StockEnricher(enrichment_providers) if enrichment_providers else None
        )

    def market_data(self):
        return self.providers.market_data()

    def news_provider(self):
        return self.domain_providers.news()

    def corporate_action_provider(self):
        return self.domain_providers.corporate_actions()

    def scanner_pipeline(self) -> FullScannerPipeline:
        return FullScannerPipeline(provider=self.market_data(), enricher=self.enricher)

    def scanner_service(self) -> ScannerService:
        return ScannerService(self.scanner_pipeline())

    def news_service(self) -> NewsService:
        return NewsService(provider=self.news_provider())

    def corporate_action_service(self) -> CorporateActionService:
        return CorporateActionService(provider=self.corporate_action_provider())

    def health(self) -> dict[str, Any]:
        service = self.scanner_service()
        return {
            "status": "healthy",
            "market_data": self.market_data().health(),
            "enrichment": self.enricher.health() if self.enricher is not None else {"status": "not_configured"},
            "scanner": service.health(),
            "domain_providers": {
                "news": type(self.news_provider()).__name__,
                "corporate_actions": type(self.corporate_action_provider()).__name__,
            },
        }


__all__ = ["ApplicationFactory"]
