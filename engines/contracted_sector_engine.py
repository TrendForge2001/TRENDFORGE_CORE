"""Contract-enforced adapter for the existing Sector Engine."""
from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.sector_contract import SectorInputContract
from engines.sector_engine import SectorEngine


class ContractedSectorEngine(BaseEngine):
    NAME = SectorEngine.NAME
    priority = getattr(SectorEngine, "priority", 6)
    mandatory = getattr(SectorEngine, "mandatory", False)

    def __init__(self, engine: SectorEngine | None = None, input_contract: SectorInputContract | None = None):
        self.engine = engine or SectorEngine()
        self.input_contract = input_contract or SectorInputContract()

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
                warnings=["Sector input contract failed"],
                metrics={"input_contract": report.as_dict()},
            )
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedSectorEngine"]
