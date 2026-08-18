"""Single orchestration layer for TrendForge analysis engines."""

from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.fundamental_engine import FundamentalEngine
from engines.risk_engine import RiskEngine
from engines.technical_engine import TechnicalEngine


class EngineOrchestrator:
    """Run the canonical engines and return a deterministic aggregate result."""

    def __init__(self, engines: list[BaseEngine] | None = None) -> None:
        self.engines = engines or [TechnicalEngine(), FundamentalEngine(), RiskEngine()]

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        results: dict[str, EngineResult] = {}
        for engine in self.engines:
            try:
                result = engine.evaluate(stock)
            except Exception as exc:
                result = EngineResult(
                    engine=engine.__class__.__name__,
                    passed=False,
                    score=0.0,
                    max_score=100.0,
                    confidence=0.0,
                    grade="ERROR",
                    warnings=[str(exc)],
                )
            results[result.engine] = result

        total_max = sum(result.max_score for result in results.values())
        total_score = sum(result.score for result in results.values())
        confidence = round((total_score / total_max) * 100, 2) if total_max else 0.0
        passed = all(result.passed for result in results.values()) if results else False

        return {
            "passed": passed,
            "score": round(total_score, 2),
            "max_score": round(total_max, 2),
            "confidence": confidence,
            "engines": {name: result.as_dict() for name, result in results.items()},
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "engines": [engine.__class__.__name__ for engine in self.engines],
        }


__all__ = ["EngineOrchestrator"]
