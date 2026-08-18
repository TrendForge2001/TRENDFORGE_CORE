"""Canonical application construction for TrendForge."""
from __future__ import annotations

from typing import Any

from api.scanner_service import ScannerService
from providers.provider_factory import ProviderFactory
from scanner.full_pipeline import FullScannerPipeline


class ApplicationFactory:
    """Build the scanner service from the canonical provider stack."""

    def __init__(self, provider_factory: ProviderFactory | None = None, **provider_kwargs: Any):
        self.providers = provider_factory or ProviderFactory(**provider_kwargs)

    def market_data(self):
        return self.providers.market_data()

    def scanner_pipeline(self) -> FullScannerPipeline:
        return FullScannerPipeline(provider=self.market_data())

    def scanner_service(self) -> ScannerService:
        return ScannerService(self.scanner_pipeline())

    def health(self) -> dict[str, Any]:
        service = self.scanner_service()
        return {
            "status": "healthy",
            "market_data": self.market_data().health(),
            "scanner": service.health(),
        }


__all__ = ["ApplicationFactory"]
