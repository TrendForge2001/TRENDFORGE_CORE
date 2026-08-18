"""Application-facing scanner service using the canonical full pipeline."""
from __future__ import annotations

from typing import Any

from scanner.full_pipeline import FullScannerPipeline


class ScannerService:
    """Thin application boundary; execution remains owned by the canonical pipeline."""

    def __init__(self, pipeline: FullScannerPipeline):
        if pipeline is None:
            raise ValueError("A FullScannerPipeline is required")
        self.pipeline = pipeline

    def scan(self, symbol: str, *, period: str = "6mo", interval: str = "1d",
             capital: float = 0.0, fundamentals: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.pipeline.analyze(symbol, period=period, interval=interval,
                                     capital=capital, fundamentals=fundamentals)

    def scan_many(self, symbols: list[str], *, period: str = "6mo", interval: str = "1d",
                  capital: float = 0.0, top_n: int = 20) -> dict[str, Any]:
        return self.pipeline.analyze_many(symbols, period=period, interval=interval,
                                          capital=capital, top_n=top_n)

    def health(self) -> dict[str, Any]:
        orchestrator = getattr(self.pipeline, "orchestrator", None)
        health = orchestrator.health() if callable(getattr(orchestrator, "health", None)) else {"status": "unknown"}
        return {"status": "healthy", "pipeline": self.pipeline.__class__.__name__, "orchestrator": health}


__all__ = ["ScannerService"]
