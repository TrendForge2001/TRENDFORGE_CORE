"""Contract boundary for the existing Big Shark Engine."""

from __future__ import annotations
from typing import Any

from engines.big_shark_contract import BigSharkInputContract
from engines.big_shark_engine import BigSharkEngine


class ContractedBigSharkEngine(BigSharkEngine):
    """Preserve the existing Big Shark scorer while enforcing its input contract."""

    def __init__(self, provider=None, repository=None, input_contract=None):
        super().__init__(provider=provider, repository=repository)
        self.input_contract = input_contract or BigSharkInputContract()

    def evaluate(self, stock: Any):
        report = self.input_contract.validate(stock)
        if not report.ready:
            from engines.base_engine import EngineResult
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
        result = super().evaluate(stock)
        result.metrics["input_contract"] = report.as_dict()
        return result


__all__ = ["ContractedBigSharkEngine"]
