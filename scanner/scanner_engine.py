"""Canonical scanner orchestration for TrendForge."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from engines.engine_orchestrator import EngineOrchestrator


@dataclass(slots=True)
class ScanResult:
    symbol: str
    score: float
    signal: str
    reasons: list[str] = field(default_factory=list)
    latest: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    engine_results: dict[str, Any] = field(default_factory=dict)
    passed: bool = False

    @property
    def overall_score(self) -> float:
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
            "engine_results": self.engine_results,
            "passed": self.passed,
        }


class ScannerEngine:
    """Run the complete TrendForge engine stack against canonical stock data."""

    def __init__(self, orchestrator: EngineOrchestrator | None = None, max_workers: int = 8) -> None:
        self.orchestrator = orchestrator or EngineOrchestrator()
        self.max_workers = max(1, int(max_workers))

    def scan(self, symbol: str, df: Any, metadata: dict[str, Any] | None = None) -> ScanResult:
        if df is None or getattr(df, "empty", True):
            return ScanResult(symbol, 0.0, "IGNORE", ["No market data"])

        stock = dict(metadata or {})
        stock["symbol"] = symbol
        stock["df"] = df
        stock.setdefault("data", df)

        evaluation = self.orchestrator.evaluate(stock)
        signal_obj = evaluation.get("signal")
        signal = getattr(signal_obj, "signal", "HOLD")
        reasons = list(getattr(signal_obj, "warnings", []) or [])
        for engine_result in evaluation.get("engines", {}).values():
            reasons.extend(engine_result.get("reasons", []))

        return ScanResult(
            symbol=symbol,
            score=float(evaluation.get("score", 0.0)),
            signal=signal,
            reasons=reasons,
            confidence=float(evaluation.get("confidence", 0.0)),
            engine_results=evaluation.get("engines", {}),
            passed=bool(evaluation.get("passed", False)),
        )

    @staticmethod
    def rank(results: list[ScanResult]) -> list[ScanResult]:
        return sorted(results, key=lambda item: (item.overall_score, item.confidence), reverse=True)

    def top_n(self, results: list[ScanResult], n: int = 20) -> list[ScanResult]:
        return self.rank(results)[:n]

    def scan_many(self, frames: dict[str, Any]) -> list[ScanResult]:
        if not frames:
            return []
        results: list[ScanResult] = []
        workers = min(self.max_workers, len(frames))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trendforge-scan") as executor:
            futures = {executor.submit(self.scan, symbol, frame): symbol for symbol, frame in frames.items()}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(ScanResult(symbol, 0.0, "IGNORE", [f"scan_error:{exc}"]))
        return self.rank(results)


__all__ = ["ScanResult", "ScannerEngine"]
