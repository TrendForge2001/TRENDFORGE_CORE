"""Canonical application construction for TrendForge."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from core.database import database_health
from core.runtime_config import runtime_configuration_health


class ApplicationFactory:
    """Build and cache application-scoped components."""

    def __init__(
        self,
        provider_factory: Any | None = None,
        domain_provider_factory: Any | None = None,
        enricher: Any | None = None,
        enrichment_providers: dict[str, Any] | None = None,
        nifty500_provider: Any | None = None,
        **provider_kwargs: Any,
    ) -> None:
        from providers.provider_factory import ProviderFactory

        if (
            provider_factory is None
            and provider_kwargs
            and "runtime_config" not in provider_kwargs
        ):
            # Explicit provider injection is an isolated/test composition; do
            # not leak host credentials into health.
            from core.runtime_config import RuntimeConfig

            provider_kwargs["runtime_config"] = RuntimeConfig()

        self.providers = provider_factory or ProviderFactory(**provider_kwargs)

        if domain_provider_factory is None:
            from core.domain_provider_factory import DomainProviderFactory

            domain_provider_factory = DomainProviderFactory()
        self.domain_providers = domain_provider_factory

        self._enrichment_snapshot_status: dict[str, Any] = {
            "status": "not_configured"
        }

        if enricher is None:
            from reconstruction.enrichment import StockEnricher

            if enrichment_providers is None:
                # Production scanner requests prefer a verified read-only
                # snapshot for slow/blockable external enrichments. Live
                # providers remain lower-priority fallbacks so local/dev
                # environments retain automatic discovery.
                from providers.enrichment_adapters import (
                    CorporateActionEnrichmentProvider,
                    YahooInstitutionalEnrichmentProvider,
                    YahooSectorEnrichmentProvider,
                )
                from providers.enrichment_snapshot_provider import (
                    EnrichmentSnapshot,
                    SnapshotFieldProvider,
                    SNAPSHOT_FIELDS,
                )
                from providers.sqlite_fundamental_provider import (
                    SQLiteFundamentalProvider,
                )
                from reconstruction.provider_registry import ProviderRegistry

                registry = ProviderRegistry()
                registry.register(
                    "fundamentals",
                    SQLiteFundamentalProvider(),
                    priority=10,
                )

                configured_path = str(
                    os.getenv("ENRICHMENT_SNAPSHOT_PATH") or ""
                ).strip()
                default_path = Path(
                    "/etc/secrets/trendforge_enrichment_snapshot.json"
                )
                snapshot_path = (
                    Path(configured_path)
                    if configured_path
                    else default_path
                    if default_path.is_file()
                    else None
                )

                if snapshot_path is not None:
                    try:
                        snapshot = EnrichmentSnapshot(
                            snapshot_path,
                            expected_sha256=os.getenv(
                                "ENRICHMENT_SNAPSHOT_SHA256"
                            ),
                        )
                        for field in SNAPSHOT_FIELDS:
                            registry.register(
                                field,
                                SnapshotFieldProvider(snapshot, field),
                                priority=10,
                                name=f"snapshot:{field}",
                            )
                        self._enrichment_snapshot_status = (
                            snapshot.health()
                        )
                    except Exception as exc:
                        self._enrichment_snapshot_status = {
                            "status": "failed",
                            "file": str(snapshot_path),
                            "error": str(exc),
                        }

                registry.register(
                    "corporate_actions",
                    CorporateActionEnrichmentProvider(
                        self.corporate_action_provider()
                    ),
                    priority=100,
                    name="live:corporate_actions",
                )
                registry.register(
                    "big_shark",
                    YahooInstitutionalEnrichmentProvider(),
                    priority=100,
                    name="live:big_shark",
                )
                registry.register(
                    "sector",
                    YahooSectorEnrichmentProvider(),
                    priority=100,
                    name="live:sector",
                )

                enricher = StockEnricher(registry=registry)
            elif enrichment_providers:
                enricher = StockEnricher(enrichment_providers)

        self.enricher = enricher
        self._nifty500_provider = nifty500_provider

        self._market_data = None
        self._scanner_pipeline = None
        self._scanner_service = None
        self._nifty500_universe = None
        self._news_service = None
        self._corporate_action_service = None
        self._fundamental_manager = None
        self._fundamental_completion = None
        self._fundamental_import_status: dict[str, Any] = {
            "status": "not_run"
        }

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
                provider=self.market_data(),
                enricher=self.enricher,
            )
        return self._scanner_pipeline

    def scanner_service(self):
        if self._scanner_service is None:
            from api.scanner_service import ScannerService

            self._scanner_service = ScannerService(
                self.scanner_pipeline()
            )
        return self._scanner_service

    def nifty500_constituent_provider(self):
        if self._nifty500_provider is None:
            from providers.nse_index_constituents import (
                NSEIndexConstituentProvider,
            )

            self._nifty500_provider = NSEIndexConstituentProvider()
        return self._nifty500_provider

    def nifty500_universe(self):
        if self._nifty500_universe is None:
            from universe.nifty500 import Nifty500Universe

            provider = self.nifty500_constituent_provider()
            loader = getattr(provider, "nifty500", None)
            if not callable(loader):
                raise TypeError(
                    "NIFTY 500 constituent provider must expose nifty500()"
                )
            self._nifty500_universe = Nifty500Universe(loader=loader)
        return self._nifty500_universe

    def news_service(self):
        if self._news_service is None:
            from services.news_service import NewsService

            self._news_service = NewsService(
                provider=self.news_provider()
            )
        return self._news_service

    def corporate_action_service(self):
        if self._corporate_action_service is None:
            from services.corporate_action_service import (
                CorporateActionService,
            )

            self._corporate_action_service = CorporateActionService(
                provider=self.corporate_action_provider(),
                require_symbol=True,
            )
        return self._corporate_action_service

    def fundamental_manager(self):
        if self._fundamental_manager is None:
            from services.fundamental_data_manager import (
                FundamentalDataManager,
            )

            self._fundamental_manager = FundamentalDataManager()
        return self._fundamental_manager

    def fundamental_completion_service(self):
        if self._fundamental_completion is None:
            from services.fundamental_completion_service import (
                FundamentalCompletionService,
            )

            self._fundamental_completion = (
                FundamentalCompletionService(
                    manager=self.fundamental_manager()
                )
            )
        return self._fundamental_completion

    def import_fundamentals_if_configured(
        self,
    ) -> dict[str, Any]:
        """Optionally refresh SQLite fundamentals from a configured local file."""

        from config import settings

        path = settings.FUNDAMENTALS_IMPORT_PATH
        if not path:
            self._fundamental_import_status = {
                "status": "not_configured"
            }
            return dict(self._fundamental_import_status)

        try:
            result = self.fundamental_manager().import_file(
                path,
                source=settings.FUNDAMENTALS_IMPORT_SOURCE,
                symbol_column=settings.FUNDAMENTALS_SYMBOL_COLUMN,
                field_map=settings.FUNDAMENTALS_FIELD_MAP_JSON,
                sheet_name=settings.FUNDAMENTALS_SHEET_NAME,
                as_of=settings.FUNDAMENTALS_AS_OF,
            )
            self._fundamental_import_status = dict(result)
        except Exception as exc:
            self._fundamental_import_status = {
                "status": "failed",
                "file": path,
                "error": str(exc),
            }

        return dict(self._fundamental_import_status)

    def health(self) -> dict[str, Any]:
        service = self.scanner_service()
        market = self.market_data()

        market_health = (
            market.health()
            if callable(getattr(market, "health", None))
            else {"status": "unknown"}
        )
        scanner_health = service.health()

        scanner_status = (
            str(
                scanner_health.get("status", "unknown")
            ).lower()
            if isinstance(scanner_health, dict)
            else "unknown"
        )
        market_status = (
            str(
                market_health.get("status", "unknown")
            ).lower()
            if isinstance(market_health, dict)
            else "unknown"
        )

        database = database_health()
        database_status = str(
            database.get("status", "unknown")
        ).lower()

        top_level_status = (
            "healthy"
            if scanner_status in {"healthy", "ok"}
            and market_status in {"healthy", "ok"}
            and database_status in {"ready", "initialized"}
            else "degraded"
        )

        enricher_health = (
            self.enricher.health()
            if self.enricher is not None
            and callable(getattr(self.enricher, "health", None))
            else {"status": "not_configured"}
        )

        universe = self.nifty500_universe()
        universe_health = universe.health()
        constituent_provider = self.nifty500_constituent_provider()
        constituent_provider_health = (
            constituent_provider.health()
            if callable(getattr(constituent_provider, "health", None))
            else {"status": "configured"}
        )

        return {
            "status": top_level_status,
            "database": database,
            "configuration": runtime_configuration_health(
                getattr(
                    self.providers,
                    "runtime_config",
                    None,
                )
            ),
            "market_data": market_health,
            "enrichment": enricher_health,
            "enrichment_snapshot": dict(
                self._enrichment_snapshot_status
            ),
            "fundamental_import": dict(
                self._fundamental_import_status
            ),
            "scanner": scanner_health,
            "universe": {
                "nifty500": universe_health,
                "provider": constituent_provider_health,
            },
            "domain_providers": {
                "news": type(
                    self.news_provider()
                ).__name__,
                "corporate_actions": type(
                    self.corporate_action_provider()
                ).__name__,
            },
        }


def build_application_factory() -> ApplicationFactory:
    """Construct the canonical application factory inside the composition root."""

    return ApplicationFactory()


__all__ = ["ApplicationFactory", "build_application_factory"]
