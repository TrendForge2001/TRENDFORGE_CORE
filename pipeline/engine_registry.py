"""Compatibility registry delegating execution to EngineOrchestrator."""

from __future__ import annotations

from typing import Any

from engines.engine_orchestrator import EngineOrchestrator


class EngineRegistry:
    """Legacy registration facade; engine execution belongs to the orchestrator."""

    def __init__(self, orchestrator: EngineOrchestrator | None = None):
        self.orchestrator = orchestrator or EngineOrchestrator(engines=[])
        self.engines = getattr(self.orchestrator, "engines", [])

    def register(self, engine: Any) -> None:
        self.engines.append(engine)

    def execute(self, stock: dict[str, Any]) -> dict[str, Any]:
        """Delegate the complete execution/aggregation contract."""
        result = self.orchestrator.evaluate(stock)
        return result.get("engines", {})

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        """Expose the canonical orchestrator result for new callers."""
        return self.orchestrator.evaluate(stock)


__all__ = ["EngineRegistry"]
