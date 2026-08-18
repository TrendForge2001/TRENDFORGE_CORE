"""Contract-enforced adapter for the existing Sector Engine."""
from __future__ import annotations
from typing import Any
from engines.sector_contract import SectorInputContract
from engines.sector_engine import SectorEngine

class ContractedSectorEngine:
    NAME = SectorEngine.NAME
    priority = getattr(SectorEngine, "priority", 6)
    mandatory = getattr(SectorEngine, "mandatory", False)
    def __init__(self, engine: SectorEngine | None = None, input_contract: SectorInputContract | None = None):
        self.engine = engine or SectorEngine()
        self.input_contract = input_contract or SectorInputContract()
    def evaluate(self, stock: dict[str, Any]):
        report = self.input_contract.validate(stock)
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        if not report.ready:
            result.passed = False
            result.score = 0.0
            result.confidence = 0.0
            result.grade = "N/A"
            result.warnings = list(result.warnings or []) + ["Sector input contract failed"]
        elif report.warnings:
            result.warnings = list(result.warnings or []) + report.warnings
        return result
    def __getattr__(self, name: str):
        return getattr(self.engine, name)

__all__ = ["ContractedSectorEngine"]
