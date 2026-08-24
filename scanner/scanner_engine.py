"""Canonical scanner orchestration for TrendForge."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from engines.data_readiness import EngineDataReadinessChecker
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
    readiness: dict[str, Any] = field(default_factory=dict)

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
            "readiness": self.readiness,
        }


class ScannerEngine:
    """Run the complete TrendForge engine stack with concurrent payload support."""

    def __init__(self, orchestrator: EngineOrchestrator | None = None,
                 readiness_checker: EngineDataReadinessChecker | None = None,
                 max_workers: int = 8) -> None:
        self.orchestrator = orchestrator or EngineOrchestrator()
        self.readiness = readiness_checker or EngineDataReadinessChecker()
        self.max_workers = max(1, int(max_workers))

    def scan(self, symbol: str, df: Any, metadata: dict[str, Any] | None = None) -> ScanResult:
        stock = dict(metadata or {})
        stock["symbol"] = symbol
        stock["df"] = df
        stock["data"] = df
        readiness = self.readiness.check(stock)
        readiness_dict = readiness.as_dict()
        if not readiness.ready:
            return ScanResult(
                symbol, 0.0, "IGNORE", list(readiness.reasons), readiness=readiness_dict
            )
        try:
            evaluation = self.orchestrator.evaluate(stock)
        except Exception as exc:
            return ScanResult(
                symbol, 0.0, "IGNORE", [f"engine_evaluation_error:{exc}"],
                readiness=readiness_dict,
            )
        signal_obj = evaluation.get("signal")
        signal = getattr(signal_obj, "signal", "HOLD")
        reasons = list(getattr(signal_obj, "warnings", []) or []) + list(readiness.warnings)
        for result in evaluation.get("engines", {}).values():
            if isinstance(result, dict):
                reasons.extend(result.get("reasons", []))
        return ScanResult(
            symbol=symbol,
            score=float(evaluation.get("score", 0.0)),
            signal=signal,
            reasons=reasons,
            confidence=float(evaluation.get("confidence", 0.0)),
            engine_results=evaluation.get("engines", {}),
            passed=bool(evaluation.get("passed", False)),
            readiness=readiness_dict,
        )

    def scan_payload(self, payload: dict[str, Any]) -> ScanResult:
        symbol = str(payload.get("symbol", ""))
        return self.scan(symbol, payload.get("df"), metadata=payload)

    def scan_payload_many(self, payloads: dict[str, dict[str, Any]], capital: float = 0) -> list[ScanResult]:
        """Evaluate enriched payloads concurrently; failures remain symbol-local."""
        if not payloads:
            return []
        results: list[ScanResult] = []
        workers = min(self.max_workers, len(payloads))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="trendforge-scan") as executor:
            futures = {
                executor.submit(self.scan_payload, payload): symbol
                for symbol, payload in payloads.items()
            }
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append(ScanResult(symbol, 0.0, "IGNORE", [f"scan_error:{exc}"]))
        return self.rank(results)

    def scan_many(self, frames: dict[str, Any]) -> list[ScanResult]:
        return self.scan_payload_many({s: {"symbol": s, "df": f} for s, f in frames.items()})

    @staticmethod
    def rank(results: list[ScanResult]) -> list[ScanResult]:
        return sorted(
            results,
            key=lambda item: (item.overall_score, item.confidence, item.symbol),
            reverse=True,
        )

    def top_n(self, results: list[ScanResult], n: int = 20) -> list[ScanResult]:
        return self.rank(results)[: max(0, int(n))]

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "max_workers": self.max_workers,
            "orchestrator_configured": self.orchestrator is not None,
            "readiness_checker_configured": self.readiness is not None,
        }


__all__ = ["ScanResult", "ScannerEngine"]
