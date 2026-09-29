"""Legacy scanner compatibility facade over FullScannerPipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scanner.full_pipeline import FullScannerPipeline


@dataclass(slots=True)
class ScanResult:
    """Legacy result shape retained for callers migrating to FullScannerPipeline."""

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
    """Compatibility API; all actual execution is delegated to FullScannerPipeline."""

    def __init__(self, orchestrator=None, readiness_checker=None, max_workers: int = 8, pipeline=None, provider=None):
        if orchestrator is not None:
            self.orchestrator = orchestrator
        if readiness_checker is not None:
            self.readiness_checker = readiness_checker
        self.pipeline = pipeline
        self.provider = provider
        self.max_workers = max(1, int(max_workers))

    def _require_pipeline(self) -> FullScannerPipeline:
        if not isinstance(self.pipeline, FullScannerPipeline):
            raise ValueError("FullScannerPipeline is required for scanner execution")
        return self.pipeline

    def scan(self, symbol: str, df: Any, metadata: dict[str, Any] | None = None) -> ScanResult:
        metadata = metadata or {}
        if getattr(self, "orchestrator", None) is not None:
            stock = {"symbol": str(symbol).strip().upper(), "df": df, "data": df, **metadata}
            if getattr(self, "readiness_checker", None) is not None:
                readiness = self.readiness_checker.check(stock)
                if not getattr(readiness, "ready", True):
                    return ScanResult(symbol=stock["symbol"], score=0.0, signal="HOLD",
                                      passed=False, readiness=getattr(readiness, "as_dict", lambda: {})())
            result = self.orchestrator.evaluate(stock)
        elif isinstance(self.pipeline, FullScannerPipeline):
            pipeline = self._require_pipeline()
            class Adapter:
                def __init__(self, frame):
                    self.frame = frame
                def candles(self, symbol, period="6mo", interval="1d"):
                    return self.frame
            canonical = FullScannerPipeline(Adapter(df), orchestrator=pipeline.orchestrator,
                indicator_engine=pipeline.indicators
            )
            result = canonical.analyze(symbol, capital=float(metadata.get("capital", 0)))
        else:
            raise ValueError("ScannerEngine requires an orchestrator or FullScannerPipeline")
        signal = result.get("signal", "HOLD")
        signal = getattr(signal, "signal", signal)
        return ScanResult(
            symbol=str(result.get("symbol", symbol)),
            score=float(result.get("score", 0.0)),
            signal=str(signal),
            confidence=float(result.get("confidence", 0.0)),
            engine_results=result.get("engines", {}),
            passed=bool(result.get("passed", False)),
            latest=result.get("snapshot", {}),
        )

    def scan_payload(self, payload: dict[str, Any]) -> ScanResult:
        return self.scan(str(payload.get("symbol", "")), payload.get("df"), metadata=payload)

    def scan_payload_many(self, payloads: dict[str, dict[str, Any]], capital: float = 0) -> list[ScanResult]:
        return [self.scan_payload({**payload, "capital": capital}) for payload in payloads.values()]

    def scan_many(self, frames: dict[str, Any]) -> list[ScanResult]:
        return self.scan_payload_many({symbol: {"symbol": symbol, "df": frame} for symbol, frame in frames.items()})

    @staticmethod
    def rank(results: list[ScanResult]) -> list[ScanResult]:
        return sorted(results, key=lambda item: (item.overall_score, item.confidence, item.symbol), reverse=True)

    def top_n(self, results: list[ScanResult], n: int = 20) -> list[ScanResult]:
        return self.rank(results)[:max(0, int(n))]


__all__ = ["ScanResult", "ScannerEngine"]
