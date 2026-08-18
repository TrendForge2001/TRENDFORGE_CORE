"""Contract adapter for the canonical Risk Engine."""
from __future__ import annotations
from typing import Any
from engines.base_engine import BaseEngine, EngineResult
from engines.risk_contract import RiskInputContract
from engines.risk_engine import RiskEngine


class ContractedRiskEngine(BaseEngine):
    NAME = RiskEngine.NAME
    mandatory = True
    priority = getattr(RiskEngine, "priority", 10)

    def __init__(self, engine: RiskEngine | None = None, input_contract: RiskInputContract | None = None):
        self.engine = engine or RiskEngine()
        self.input_contract = input_contract or RiskInputContract()

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(
                engine=self.NAME,
                passed=False,
                score=0.0,
                max_score=100.0,
                confidence=0.0,
                grade="N/A",
                reasons=[],
                warnings=["Risk input contract failed"],
                metrics={"input_contract": report.as_dict()},
            )
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedRiskEngine"]
