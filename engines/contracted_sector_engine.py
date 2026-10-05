"""Contract-enforced adapter for the canonical Sector Engine."""
from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.sector_contract import SectorInputContract
from engines.canonical_nontechnical_engines import CanonicalSectorEngine


class ContractedSectorEngine(BaseEngine):
    NAME = CanonicalSectorEngine.NAME
    priority = getattr(CanonicalSectorEngine, "priority", 6)
    mandatory = getattr(CanonicalSectorEngine, "mandatory", False)

    def __init__(self, engine: CanonicalSectorEngine | None = None, input_contract: SectorInputContract | None = None):
        self.engine = engine or CanonicalSectorEngine()
        self.input_contract = input_contract or SectorInputContract()

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0, max_score=100.0,
                                 confidence=0.0, grade="N/A", warnings=["Sector input contract failed"],
                                 metrics={"input_contract": report.as_dict()})
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedSectorEngine"]
