"""Contract adapter for the existing Price Action Engine."""
from __future__ import annotations
from typing import Any
from engines.base_engine import BaseEngine, EngineResult
from engines.price_action_contract import PriceActionInputContract
from engines.price_action_engine import PriceActionEngine

class ContractedPriceActionEngine(BaseEngine):
    NAME = PriceActionEngine.NAME
    def __init__(self, engine: PriceActionEngine | None = None, input_contract: PriceActionInputContract | None = None):
        self.engine = engine or PriceActionEngine()
        self.input_contract = input_contract or PriceActionInputContract()
    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0, max_score=100.0, confidence=0.0,
                                grade="N/A", warnings=["Price action input contract failed"],
                                metrics={"input_contract": report.as_dict()})
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

__all__ = ["ContractedPriceActionEngine"]
