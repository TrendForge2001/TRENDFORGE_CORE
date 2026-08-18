"""Contract adapter for the canonical Big Shark Engine."""
from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.big_shark_contract import BigSharkInputContract
from engines.big_shark_engine import BigSharkEngine


class ContractedBigSharkEngine(BaseEngine):
    """Validate Big Shark inputs before delegating to the existing scorer."""

    NAME = BigSharkEngine.NAME
    priority = getattr(BigSharkEngine, "priority", 5)
    mandatory = getattr(BigSharkEngine, "mandatory", False)

    def __init__(self, provider=None, repository=None, input_contract=None, engine=None):
        self.engine = engine or BigSharkEngine(provider=provider, repository=repository)
        self.input_contract = input_contract or BigSharkInputContract()

    def evaluate(self, stock: Any) -> EngineResult:
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
                warnings=["Big Shark input contract failed"],
                metrics={"input_contract": report.as_dict()},
            )
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedBigSharkEngine"]
