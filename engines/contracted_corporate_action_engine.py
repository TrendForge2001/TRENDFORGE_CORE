"""Contract adapter for the canonical Corporate Action Engine."""
from __future__ import annotations
from typing import Any
from engines.base_engine import BaseEngine, EngineResult
from engines.corporate_action_contract import CorporateActionInputContract
from engines.corporate_action_engine import CorporateActionEngine


class ContractedCorporateActionEngine(BaseEngine):
    NAME = CorporateActionEngine.NAME
    priority = getattr(CorporateActionEngine, "priority", 4)
    mandatory = getattr(CorporateActionEngine, "mandatory", False)

    def __init__(
        self,
        engine: CorporateActionEngine | None = None,
        input_contract: CorporateActionInputContract | None = None,
    ) -> None:
        self.engine = engine or CorporateActionEngine()
        self.input_contract = input_contract or CorporateActionInputContract()

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
                warnings=["Corporate action input contract failed"],
                metrics={"input_contract": report.as_dict()},
            )

        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedCorporateActionEngine"]
