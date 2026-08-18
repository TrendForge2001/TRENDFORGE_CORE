"""Compatibility bridge from the legacy pipeline API to the canonical engine orchestrator."""
from __future__ import annotations
from typing import Any, List

from engines.engine_orchestrator import EngineOrchestrator


class TrendForgePipeline:
    """Preserve register/execute compatibility while using the rebuilt pipeline."""

    def __init__(self, orchestrator: EngineOrchestrator | None = None):
        self.orchestrator = orchestrator or EngineOrchestrator()
        self.engines: List[Any] = self.orchestrator.engines

    def register(self, engine: Any) -> None:
        """Register an additional engine without replacing the canonical chain."""
        self.engines.append(engine)

    def execute(self, stock: dict[str, Any]) -> dict[str, Any]:
        """Execute the canonical orchestrator and expose legacy-compatible results."""
        result = self.orchestrator.evaluate(stock)
        engine_results = list(result.get("engines", {}).values())
        return {
            "results": engine_results,
            "score": result.get("score", 0.0),
            "max_score": result.get("max_score", 0.0),
            "confidence": result.get("confidence", 0.0),
            "signal": result.get("signal"),
            "passed": result.get("passed", False),
            "input_contract": result.get("input_contract", {}),
        }

    def health(self) -> dict[str, Any]:
        return self.orchestrator.health()


__all__ = ["TrendForgePipeline"]
