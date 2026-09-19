"""Runnable scanner service wiring the canonical TrendForge pipeline."""
from __future__ import annotations

from typing import Any, Iterable

from pipeline.scan_pipeline import ScanPipeline
from providers.market_data_adapter import MarketDataAdapter
from scanner.ranking import RankingEngine
from scanner.scanner_engine import ScannerEngine
from scanner.top_picks import TopPicks
from services.dashboard_service import DashboardService
from universe.data_validation import MarketDataValidator


class ScannerService:
    """Application-facing scanner facade with explicit dependency injection."""

    def __init__(self, provider: Any, scanner=None, ranking=None, dashboard=None,
                 top_picks=None, data_validator=None, max_workers: int = 8) -> None:
        self.provider = provider
        self.adapter = MarketDataAdapter(provider, max_workers=max_workers)
        self.pipeline = ScanPipeline(
            scanner=scanner or ScannerEngine(max_workers=max_workers),
            ranking=ranking or RankingEngine(),
            dashboard=dashboard or DashboardService(),
            top_picks=top_picks or TopPicks(),
            data_validator=data_validator or MarketDataValidator(min_rows=1),
            market_data_adapter=self.adapter,
        )

    def scan(self, symbols: Iterable[str], capital: float = 0, top_n: int = 20) -> dict[str, Any]:
        symbols = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        if not symbols:
            raise ValueError("At least one symbol is required for scanning")
        return self.pipeline.run(symbols=symbols, capital=capital, top_n=top_n)

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "provider": self.adapter.health(),
            "pipeline": self.pipeline.health(),
        }


__all__ = ["ScannerService"]
