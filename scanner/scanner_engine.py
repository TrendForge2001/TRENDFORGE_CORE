"""Legacy scanner compatibility facade over the canonical pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from scanner.full_pipeline import FullScannerPipeline


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
    def overall_score(self):
        return self.score

    def as_dict(self):
        return {
            "symbol": self.symbol, "score": self.score,
            "overall_score": self.overall_score, "signal": self.signal,
            "reasons": self.reasons, "latest": self.latest,
            "confidence": self.confidence, "engine_results": self.engine_results,
            "passed": self.passed, "readiness": self.readiness,
        }


class ScannerEngine:
    def __init__(self, orchestrator=None, readiness_checker=None, max_workers=8,
                 pipeline=None, provider=None):
        self.orchestrator = orchestrator
        self.pipeline = pipeline
        self.max_workers = max(1, int(max_workers))
        if self.pipeline is None and provider is not None:
            self.pipeline = FullScannerPipeline(provider=provider, orchestrator=orchestrator)

    def _require_pipeline(self):
        if self.pipeline is None:
            raise ValueError("FullScannerPipeline is required for scanner execution")
        return self.pipeline

    def scan(self, symbol: str, df: Any, metadata=None):
        pipeline = self._require_pipeline()
        if pipeline.provider is not None and not hasattr(pipeline.provider, "candles"):
            class Adapter:
                def __init__(self, frame): self.frame = frame
                def candles(self, symbol, period="6mo", interval="1d"): return self.frame
            pipeline = FullScannerPipeline(
                Adapter(df), orchestrator=pipeline.orchestrator,
                indicator_engine=pipeline.indicators,
            )
        else:
            original = pipeline.provider
            class FrameProvider:
                def candles(self, symbol, period="6mo", interval="1d"): return df
            if not hasattr(original, "candles"):
                pipeline = FullScannerPipeline(
                    FrameProvider(df), orchestrator=pipeline.orchestrator,
                    indicator_engine=pipeline.indicators,
                )
        result = pipeline.analyze(symbol, capital=float((metadata or {}).get("capital", 0)))
        signal = getattr(result.get("signal", "HOLD"), "signal", result.get("signal", "HOLD"))
        return ScanResult(
            symbol=str(result.get("symbol", symbol)),
            score=float(result.get("score", 0)),
            signal=str(signal),
            confidence=float(result.get("confidence", 0)),
            engine_results=result.get("engines", {}),
            passed=bool(result.get("passed", False)),
            latest=result.get("snapshot", {}),
        )

    def scan_payload(self, payload):
        return self.scan(str(payload.get("symbol", "")), payload.get("df"), metadata=payload)

    def scan_payload_many(self, payloads, capital=0):
        return [self.scan_payload({**payload, "capital": capital}) for payload in payloads.values()]

    def scan_many(self, frames):
        return self.scan_payload_many(
            {symbol: {"symbol": symbol, "df": frame} for symbol, frame in frames.items()}
        )

    @staticmethod
    def rank(results):
        return sorted(results, key=lambda item: (item.overall_score, item.confidence, item.symbol), reverse=True)

    def top_n(self, results, n=20):
        return self.rank(results)[:max(0, int(n))]


__all__ = ["ScanResult", "ScannerEngine"]
