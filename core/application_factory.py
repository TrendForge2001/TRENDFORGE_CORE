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
    """Build and cache application-scoped canonical components."""

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
        self._market_data = None
        self._scanner_pipeline: FullScannerPipeline | None = None
        self._scanner_service: ScannerService | None = None
        self._news_service: NewsService | None = None
        self._corporate_action_service: CorporateActionService | None = None

    def market_data(self):
        if self._market_data is None:
            self._market_data = self.providers.market_data()
        return self._market_data

    def news_provider(self):
        return self.domain_providers.news()

    def corporate_action_provider(self):
        return self.domain_providers.corporate_actions()

    def scanner_pipeline(self) -> FullScannerPipeline:
        if self._scanner_pipeline is None:
            self._scanner_pipeline = FullScannerPipeline(
                provider=self.market_data(), enricher=self.enricher
            )
        return self._scanner_pipeline

    def scanner_service(self) -> ScannerService:
        if self._scanner_service is None:
            self._scanner_service = ScannerService(self.scanner_pipeline())
        return self._scanner_service

    def news_service(self) -> NewsService:
        if self._news_service is None:
            self._news_service = NewsService(provider=self.news_provider())
        return self._news_service

    def corporate_action_service(self) -> CorporateActionService:
        if self._corporate_action_service is None:
            self._corporate_action_service = CorporateActionService(
                provider=self.corporate_action_provider()
            )
        return self._corporate_action_service

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
