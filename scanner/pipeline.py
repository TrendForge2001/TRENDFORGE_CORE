"""Market-data to scanner pipeline."""

from __future__ import annotations

from typing import Any

from scanner.scanner_engine import ScanResult, ScannerEngine


class ScannerPipeline:
    """Fetch market data and run the canonical scanner without embedding provider logic in the scanner."""

    def __init__(self, provider: Any, scanner: ScannerEngine | None = None) -> None:
        self.provider = provider
        self.scanner = scanner or ScannerEngine()

    def scan_symbol(self, symbol: str, period: str = "6mo", interval: str = "1d") -> ScanResult:
        frame = self.provider.candles(symbol, period=period, interval=interval)
        return self.scanner.scan(symbol, frame)

    def scan_many(self, symbols: list[str], period: str = "6mo", interval: str = "1d") -> list[ScanResult]:
        results: list[ScanResult] = []
        for symbol in symbols:
            try:
                results.append(self.scan_symbol(symbol, period=period, interval=interval))
            except Exception as exc:
                results.append(ScanResult(symbol, 0.0, "ERROR", [str(exc)], {}, 0.0))
        return self.scanner.rank(results)

    def top_n(self, symbols: list[str], n: int = 20, period: str = "6mo", interval: str = "1d") -> list[ScanResult]:
        return self.scan_many(symbols, period=period, interval=interval)[:n]


__all__ = ["ScannerPipeline"]
