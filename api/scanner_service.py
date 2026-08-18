"""Application service boundary for canonical TrendForge scanning."""
from __future__ import annotations

from typing import Any, Mapping

from scanner.scanner_engine import ScanResult, ScannerEngine


class ScannerService:
    """Expose scanner operations without allowing callers to bypass ScannerEngine."""

    def __init__(self, scanner: ScannerEngine | None = None, max_workers: int = 8) -> None:
        self.scanner = scanner or ScannerEngine(max_workers=max_workers)

    def scan(self, symbol: str, df: Any, metadata: Mapping[str, Any] | None = None) -> ScanResult:
        return self.scanner.scan(symbol, df, metadata=dict(metadata or {}))

    def scan_payload(self, payload: Mapping[str, Any]) -> ScanResult:
        return self.scanner.scan_payload(dict(payload))

    def scan_many(self, frames: Mapping[str, Any]) -> list[ScanResult]:
        return self.scanner.scan_many(dict(frames))

    def scan_payload_many(self, payloads: Mapping[str, Mapping[str, Any]]) -> list[ScanResult]:
        return self.scanner.scan_payload_many({symbol: dict(payload) for symbol, payload in payloads.items()})

    def top_n(self, results: list[ScanResult], n: int = 20) -> list[ScanResult]:
        return self.scanner.top_n(results, n=n)

    def health(self) -> dict[str, Any]:
        orchestrator = self.scanner.orchestrator
        return {
            "status": "healthy",
            "service": self.__class__.__name__,
            "scanner": self.scanner.__class__.__name__,
            "orchestrator": orchestrator.health(),
        }


__all__ = ["ScannerService"]
