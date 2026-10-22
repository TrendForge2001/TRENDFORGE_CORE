"""Canonical application construction for TrendForge."""
from __future__ import annotations

import os
import threading
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
                big_shark_live_fallback = str(
                    os.getenv(
                        "BIG_SHARK_LIVE_FALLBACK_ENABLED",
                        "true",
                    )
                ).strip().lower() in {"1", "true", "yes", "on"}

                if big_shark_live_fallback:
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
        self._finedge_fundamentals = None
        self._finedge_lock = threading.Lock()
        self._fundamental_completion = None
        self._fundamental_coverage = None
        self._fundamental_bulk_ingestion = None
        self._scan_run_audit = None
        self._scan_continuation = None
        self._paper_trading = None
        self._paper_quote_monitor = None
        self._paper_auto_entry = None
        self._strategy_driven_paper = None
        self._strategy_paper_monitor = None
        self._strategy_runtime_state = None
        self._strategy_runtime_reconciliation = None
        self._portfolio_performance = None
        self._watchlist_dashboard = None
        self._market_context = None
        self._backtest_service = None
        self._technical_trading = None
        self._multi_strategy_scanner = None
        self._intelligence_dashboard = None
        self._institutional_activity_provider = None
        self._institutional_sector = None
        self._notification_center = None
        self._notification_producer = None
        self._notification_policy = None
        self._notification_daily_summary = None
        self._notification_summary_scheduler = None
        self._market_day_operations = None
        self._market_day_operations_scheduler = None
        self._operations_reliability = None
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

    def finedge_fundamental_service(self):
        with self._finedge_lock:
            if self._finedge_fundamentals is None:
                from services.finedge_fundamental_service import FinEdgeFundamentalService

                self._finedge_fundamentals = FinEdgeFundamentalService()
            return self._finedge_fundamentals

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
                    manager=self.fundamental_manager(),
                    universe=self.nifty500_universe(),
                )
            )
        return self._fundamental_completion

    def fundamental_coverage_service(self):
        if self._fundamental_coverage is None:
            from services.fundamental_coverage_service import (
                FundamentalCoverageService,
            )

            self._fundamental_coverage = FundamentalCoverageService(
                manager=self.fundamental_manager(),
                universe=self.nifty500_universe(),
            )
        return self._fundamental_coverage

    def fundamental_bulk_ingestion_service(self):
        if self._fundamental_bulk_ingestion is None:
            from services.fundamental_bulk_ingestion_service import (
                FundamentalBulkIngestionService,
            )

            self._fundamental_bulk_ingestion = (
                FundamentalBulkIngestionService(
                    completion=self.fundamental_completion_service(),
                    coverage=self.fundamental_coverage_service(),
                )
            )
        return self._fundamental_bulk_ingestion

    def scan_run_audit_service(self):
        if self._scan_run_audit is None:
            from services.scan_run_audit_service import (
                ScanRunAuditService,
            )

            self._scan_run_audit = ScanRunAuditService()
        return self._scan_run_audit

    def scan_continuation_service(self):
        if self._scan_continuation is None:
            from services.scan_continuation_service import (
                ScanContinuationService,
            )

            self._scan_continuation = ScanContinuationService()
        return self._scan_continuation

    def paper_trading_service(self):
        if self._paper_trading is None:
            from services.paper_trading_service import (
                PaperTradingService,
            )

            self._paper_trading = PaperTradingService(
                notifications=self.notification_producer_service(),
            )
        return self._paper_trading

    def paper_quote_monitor(self):
        if self._paper_quote_monitor is None:
            from services.paper_quote_monitor import PaperQuoteMonitor

            quote_factory = getattr(
                self.providers,
                "quote",
                None,
            )
            quote_provider = (
                quote_factory()
                if callable(quote_factory)
                else None
            )
            strategy_monitor = None
            try:
                strategy_monitor = self.strategy_paper_monitor_service()
            except Exception:
                # Strategy-aware exits are additive. Legacy/manual paper
                # monitoring must remain constructible in isolated tests and
                # environments without the R72.5 Kite scanner dependency.
                strategy_monitor = None
            self._paper_quote_monitor = PaperQuoteMonitor(
                self.paper_trading_service(),
                quote_provider,
                notifications=self.notification_producer_service(),
                strategy_monitor=strategy_monitor,
            )
        return self._paper_quote_monitor

    def paper_auto_entry_service(self):
        if self._paper_auto_entry is None:
            from services.paper_auto_entry_service import (
                PaperAutoEntryService,
            )

            self._paper_auto_entry = PaperAutoEntryService(
                self.paper_trading_service(),
                notifications=self.notification_producer_service(),
            )
        return self._paper_auto_entry

    def strategy_runtime_state_repository(self):
        if self._strategy_runtime_state is None:
            from database.repositories.strategy_runtime_state_repository import (
                StrategyRuntimeStateRepository,
            )

            self._strategy_runtime_state = StrategyRuntimeStateRepository()
        return self._strategy_runtime_state

    def strategy_driven_paper_service(self):
        if self._strategy_driven_paper is None:
            from services.strategy_driven_paper_service import (
                StrategyDrivenPaperService,
            )

            self._strategy_driven_paper = StrategyDrivenPaperService(
                scanner_service=self.multi_strategy_scanner_service(),
                paper_auto_entry=self.paper_auto_entry_service(),
                state_repository=self.strategy_runtime_state_repository(),
            )
        return self._strategy_driven_paper

    def strategy_paper_monitor_service(self):
        if self._strategy_paper_monitor is None:
            from services.strategy_paper_monitor_service import (
                StrategyPaperMonitorService,
            )

            quote_factory = getattr(
                self.providers,
                "quote",
                None,
            )
            quote_provider = (
                quote_factory()
                if callable(quote_factory)
                else None
            )
            self._strategy_paper_monitor = StrategyPaperMonitorService(
                scanner_service=self.multi_strategy_scanner_service(),
                paper_service=self.paper_trading_service(),
                quote_provider=quote_provider,
            )
        return self._strategy_paper_monitor

    def strategy_runtime_reconciliation_service(self):
        if self._strategy_runtime_reconciliation is None:
            from services.strategy_runtime_reconciliation_service import (
                StrategyRuntimeReconciliationService,
            )

            from api.production_runtime import storage_health

            self._strategy_runtime_reconciliation = (
                StrategyRuntimeReconciliationService(
                    state_repository=self.strategy_runtime_state_repository(),
                    paper_service=self.paper_trading_service(),
                    storage_health_getter=storage_health,
                )
            )
        return self._strategy_runtime_reconciliation

    def portfolio_performance_service(self):
        if self._portfolio_performance is None:
            from services.portfolio_performance_service import (
                PortfolioPerformanceService,
            )

            broker = None
            configured_broker = getattr(
                self.providers,
                "kite",
                None,
            )
            runtime_config = getattr(
                self.providers,
                "runtime_config",
                None,
            )
            kite_authenticated = bool(
                getattr(
                    runtime_config,
                    "kite_authenticated",
                    False,
                )
            )
            if configured_broker is not None:
                broker = configured_broker
            elif kite_authenticated:
                default_kite = getattr(
                    self.providers,
                    "_default_kite",
                    None,
                )
                if callable(default_kite):
                    broker = default_kite()

            self._portfolio_performance = (
                PortfolioPerformanceService(
                    broker=broker,
                )
            )
        return self._portfolio_performance

    def watchlist_dashboard_service(self):
        if self._watchlist_dashboard is None:
            from services.watchlist_dashboard_service import (
                WatchlistDashboardService,
            )

            self._watchlist_dashboard = WatchlistDashboardService()
        return self._watchlist_dashboard

    def market_context_service(self):
        if self._market_context is None:
            from services.market_context_service import (
                MarketContextService,
            )

            self._market_context = MarketContextService(
                market_data=self.market_data(),
                universe=self.nifty500_universe(),
            )
        return self._market_context

    def backtest_service(self):
        if self._backtest_service is None:
            from services.backtest_service import BacktestService

            self._backtest_service = BacktestService(
                market_data=self.market_data(),
            )
        return self._backtest_service

    def technical_trading_service(self):
        if self._technical_trading is None:
            from services.technical_trading_service import (
                TechnicalTradingService,
            )

            strict_kite = getattr(
                self.providers,
                "kite_market_data",
                None,
            )
            if not callable(strict_kite):
                raise RuntimeError(
                    "Provider factory does not expose Kite-only market data"
                )
            self._technical_trading = TechnicalTradingService(
                market_data=strict_kite(),
                paper_auto_entry=self.paper_auto_entry_service(),
            )
        return self._technical_trading

    def multi_strategy_scanner_service(self):
        if self._multi_strategy_scanner is None:
            from services.multi_strategy_nifty_scanner import (
                MultiStrategyNiftyScanner,
            )

            strict_kite = getattr(
                self.providers,
                "kite_market_data",
                None,
            )
            if not callable(strict_kite):
                raise RuntimeError(
                    "Provider factory does not expose Kite-only market data"
                )
            self._multi_strategy_scanner = MultiStrategyNiftyScanner(
                market_data=strict_kite(),
                state_repository=self.strategy_runtime_state_repository(),
            )
        return self._multi_strategy_scanner

    def institutional_activity_provider(self):
        if self._institutional_activity_provider is None:
            from providers.enrichment_adapters import (
                YahooInstitutionalEnrichmentProvider,
            )

            self._institutional_activity_provider = (
                YahooInstitutionalEnrichmentProvider()
            )
        return self._institutional_activity_provider

    def institutional_sector_service(self):
        if self._institutional_sector is None:
            from services.institutional_sector_service import (
                InstitutionalSectorService,
            )

            self._institutional_sector = InstitutionalSectorService(
                institutional_provider=(
                    self.institutional_activity_provider()
                ),
                market_data=self.market_data(),
                universe=self.nifty500_universe(),
            )
        return self._institutional_sector

    def market_day_operations_service(self):
        if self._market_day_operations is None:
            from services.market_day_operations_service import (
                MarketDayOperationsService,
            )

            self._market_day_operations = MarketDayOperationsService(
                market_context=self.market_context_service(),
                paper_monitor=self.paper_quote_monitor(),
                portfolio=self.portfolio_performance_service(),
                notification_center=self.notification_center_service(),
            )
        return self._market_day_operations

    def market_day_operations_scheduler(self):
        if self._market_day_operations_scheduler is None:
            from services.market_day_operations_scheduler import (
                MarketDayOperationsScheduler,
            )

            self._market_day_operations_scheduler = (
                MarketDayOperationsScheduler(
                    operations_service=(
                        self.market_day_operations_service()
                    ),
                )
            )
        return self._market_day_operations_scheduler

    def operations_reliability_service(self):
        if self._operations_reliability is None:
            from services.operations_reliability_service import (
                OperationsReliabilityService,
            )

            operations = self.market_day_operations_service()
            self._operations_reliability = OperationsReliabilityService(
                operations_service=operations,
                repository=operations.repository,
                notification_center=self.notification_center_service(),
            )
        return self._operations_reliability

    def notification_policy_service(self):
        if self._notification_policy is None:
            from services.notification_policy_service import (
                NotificationPolicyService,
            )

            self._notification_policy = NotificationPolicyService()
        return self._notification_policy

    def notification_daily_summary_service(self):
        if self._notification_daily_summary is None:
            from services.notification_daily_summary_service import (
                NotificationDailySummaryService,
            )

            self._notification_daily_summary = (
                NotificationDailySummaryService(
                    center=self.notification_center_service(),
                    policy=self.notification_policy_service(),
                )
            )
        return self._notification_daily_summary

    def notification_summary_scheduler(self):
        if self._notification_summary_scheduler is None:
            from services.notification_daily_summary_scheduler import (
                NotificationDailySummaryScheduler,
            )

            self._notification_summary_scheduler = (
                NotificationDailySummaryScheduler(
                    summary_service=(
                        self.notification_daily_summary_service()
                    ),
                    policy_service=(
                        self.notification_policy_service()
                    ),
                )
            )
        return self._notification_summary_scheduler

    def notification_producer_service(self):
        if self._notification_producer is None:
            from services.notification_producer_service import (
                NotificationProducerService,
            )

            self._notification_producer = NotificationProducerService(
                self.notification_center_service(),
            )
        return self._notification_producer

    def notification_center_service(self):
        if self._notification_center is None:
            from services.discord_service import DiscordService
            from services.notification_center_service import (
                NotificationCenterService,
            )

            runtime_config = getattr(
                self.providers,
                "runtime_config",
                None,
            )
            webhook = getattr(
                runtime_config,
                "discord_webhook",
                None,
            )
            self._notification_center = NotificationCenterService(
                discord=DiscordService(
                    webhook_url=webhook,
                ),
                policy=self.notification_policy_service(),
            )
        return self._notification_center

    def intelligence_dashboard_service(self):
        if self._intelligence_dashboard is None:
            from services.intelligence_dashboard_service import (
                IntelligenceDashboardService,
            )

            self._intelligence_dashboard = (
                IntelligenceDashboardService(
                    news_service=self.news_service(),
                    corporate_action_service=(
                        self.corporate_action_service()
                    ),
                )
            )
        return self._intelligence_dashboard

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

        audit_service = self.scan_run_audit_service()
        audit_health = (
            audit_service.health()
            if callable(getattr(audit_service, "health", None))
            else {"status": "unknown"}
        )
        continuation_service = self.scan_continuation_service()
        continuation_health = (
            continuation_service.health()
            if callable(
                getattr(continuation_service, "health", None)
            )
            else {"status": "unknown"}
        )
        paper_trading = self.paper_trading_service()
        paper_trading_health = (
            paper_trading.health()
            if callable(
                getattr(paper_trading, "health", None)
            )
            else {"status": "unknown"}
        )
        paper_quote_monitor = self.paper_quote_monitor()
        paper_quote_monitor_health = (
            paper_quote_monitor.health()
            if callable(
                getattr(paper_quote_monitor, "health", None)
            )
            else {"status": "unknown"}
        )
        paper_auto_entry = self.paper_auto_entry_service()
        paper_auto_entry_health = (
            paper_auto_entry.health()
            if callable(
                getattr(paper_auto_entry, "health", None)
            )
            else {"status": "unknown"}
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
            "observability": {
                "scan_run_audit": audit_health,
                "scan_continuations": continuation_health,
            },
            "execution": {
                "paper_trading": paper_trading_health,
                "paper_quote_monitor": paper_quote_monitor_health,
                "paper_auto_entry": paper_auto_entry_health,
            },
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
