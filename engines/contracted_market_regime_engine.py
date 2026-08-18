"""Contract-enforced adapter for the existing Market Regime Engine."""

from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.market_regime_contract import MarketRegimeInputContract
from engines.market_regime_engine import MarketRegimeEngine


class ContractedMarketRegimeEngine(BaseEngine):
    """Validate market-regime inputs before delegating to the canonical engine."""

    NAME = MarketRegimeEngine.NAME
    mandatory = True

    def __init__(
        self,
        engine: MarketRegimeEngine | None = None,
        input_contract: MarketRegimeInputContract | None = None,
    ) -> None:
        self.engine = engine or MarketRegimeEngine()
        self.input_contract = input_contract or MarketRegimeInputContract()

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
                warnings=["Market regime input contract failed"],
                metrics={"input_contract": report.as_dict()},
            )

        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.warnings = list(result.warnings or []) + list(report.warnings)
        return result


__all__ = ["ContractedMarketRegimeEngine"]
