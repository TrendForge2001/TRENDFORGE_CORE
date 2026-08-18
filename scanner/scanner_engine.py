"""Canonical scanner orchestration for TrendForge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from indicators.indicator_engine import IndicatorEngine


@dataclass(slots=True)
class ScanResult:
    symbol: str
    score: float
    signal: str
    reasons: list[str] = field(default_factory=list)
    latest: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0

    @property
    def overall_score(self) -> float:
        """Canonical ranking alias used by RankingEngine."""
        return self.score

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "overall_score": self.overall_score,
            "signal": self.signal,
            "reasons": self.reasons,
            "latest": self.latest,
            "confidence": self.confidence,
        }


class ScannerEngine:
    """Run technical scan rules against canonical OHLCV frames."""

    def __init__(self, fundamental_service: Any = None, indicator_engine: Any = None, max_workers: int = 8) -> None:
        self.indicators = indicator_engine or IndicatorEngine()
        self.fundamentals = fundamental_service
        self.max_workers = max(1, int(max_workers))

    def scan(self, symbol: str, df: Any, fundamentals: Any = None) -> ScanResult:
        if df is None or getattr(df, "empty", True):
            return ScanResult(symbol, 0.0, "IGNORE", ["No market data"], {}, 0.0)

        data = self.indicators.calculate(df.copy())
        row = data.iloc[-1]
        score = 0.0
        reasons: list[str] = []

        def add(condition: bool, points: float, reason: str) -> None:
            nonlocal score
            if condition:
                score += points
                reasons.append(reason)

        add(row.get("EMA_20", 0) > row.get("EMA_50", 0), 20, "EMA20 above EMA50")
        add(row.get("EMA_50", 0) > row.get("EMA_200", 0), 20, "EMA50 above EMA200")
        add(row.get("RSI", 0) >= 55, 10, "RSI bullish")
        add(row.get("MACD", 0) > row.get("MACD_SIGNAL", 0), 15, "MACD bullish")
        add(row.get("ADX", 0) > 25, 10, "ADX trend strength")
        add(row.get("RVOL", 0) >= 1.5, 10, "Relative volume elevated")
        add(bool(row.get("BREAKOUT", False)), 15, "Breakout")

        score = min(100.0, score)
        signal = "STRONG BUY" if score >= 80 else "BUY" if score >= 60 else "WATCH" if score >= 40 else "IGNORE"
        return ScanResult(symbol, score, signal, reasons, row.to_dict(), score)

    @staticmethod
    def rank(results: list[ScanResult]) -> list[ScanResult]:
        return sorted(results, key=lambda item: (item.overall_score, item.confidence), reverse=True)

    def top_n(self, results: list[ScanResult], n: int = 20) -> list[ScanResult]:
        return self.rank(results)[:n]

    def scan_many(self, frames: dict[str, Any]) -> list[ScanResult]:
        """Analyze validated frames concurrently with bounded workers.

        Exceptions are isolated to the affected symbol and represented as an
        IGNORE result so one malformed frame cannot terminate a full scan.
        """
        if not frames:
            return []

        results: list[ScanResult] = []
        workers = min(self.max_workers, len(frames))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trendforge-scan") as executor:
            futures = {
                executor.submit(self.scan, symbol, frame): symbol
                for symbol, frame in frames.items()
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(
                        ScanResult(
                            symbol,
                            0.0,
                            "IGNORE",
                            [f"scan_error:{exc}"],
                            {},
                            0.0,
                        )
                    )

        return self.rank(results)
