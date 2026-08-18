"""Contract adapter for the canonical Fundamental Engine."""
from __future__ import annotations
from typing import Any
from engines.base_engine import BaseEngine, EngineResult
from engines.fundamental_contract import FundamentalInputContract
from engines.fundamental_engine import FundamentalEngine

class ContractedFundamentalEngine(BaseEngine):
    NAME = FundamentalEngine.NAME
    mandatory = True
    priority = getattr(FundamentalEngine, "priority", 4)

    def __init__(self, engine: FundamentalEngine | None = None, input_contract: FundamentalInputContract | None = None):
        self.engine = engine or FundamentalEngine()
        self.input_contract = input_contract or FundamentalInputContract()

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0,
                                max_score=self.engine.MAX_SCORE, confidence=0.0,
                                grade="N/A", reasons=[],
                                warnings=["Fundamental input contract failed"],
                                metrics={"input_contract": report.as_dict()})
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)

__all__ = ["ContractedFundamentalEngine"]
