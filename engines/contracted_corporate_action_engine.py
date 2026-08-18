"""Contract adapter for the canonical Corporate Action Engine."""
from __future__ import annotations
from typing import Any
from engines.base_engine import BaseEngine, EngineResult
from engines.corporate_action_engine import CorporateActionEngine


class ContractedCorporateActionEngine(BaseEngine):
    NAME = CorporateActionEngine.NAME
    priority = getattr(CorporateActionEngine, "priority", 4)
    mandatory = getattr(CorporateActionEngine, "mandatory", False)

    def __init__(self, engine: CorporateActionEngine | None = None) -> None:
        self.engine = engine or CorporateActionEngine()

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        return self.engine.evaluate(stock)

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedCorporateActionEngine"]
