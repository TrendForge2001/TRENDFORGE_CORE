"""Canonical application construction for TrendForge."""
from __future__ import annotations

from typing import Any

from api.scanner_service import ScannerService
from providers.provider_factory import ProviderFactory
from scanner.full_pipeline import FullScannerPipeline
from reconstruction.enrichment import StockEnricher


class ApplicationFactory:
    """Build the scanner service from canonical market-data and enrichment stacks."""

    def __init__(self, provider_factory: ProviderFactory | None = None,
                 enricher: StockEnricher | None = None,
                 enrichment_providers: dict[str, Any] | None = None,
                 **provider_kwargs: Any):
        self.providers = provider_factory or ProviderFactory(**provider_kwargs)
        self.enricher = enricher or (StockEnricher(enrichment_providers) if enrichment_providers else None)

    def market_data(self):
        return self.providers.market_data()

    def scanner_pipeline(self) -> FullScannerPipeline:
        return FullScannerPipeline(provider=self.market_data(), enricher=self.enricher)

    def scanner_service(self) -> ScannerService:
        return ScannerService(self.scanner_pipeline())

    def health(self) -> dict[str, Any]:
        service = self.scanner_service()
        return {
            "status": "healthy",
            "market_data": self.market_data().health(),
            "enrichment": self.enricher.health() if self.enricher is not None else {"status": "not_configured"},
            "scanner": service.health(),
        }


__all__ = ["ApplicationFactory"]
