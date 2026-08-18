"""Contract-enforced adapter for the existing Market Regime Engine."""

from __future__ import annotations

from typing import Any

from engines.market_regime_contract import MarketRegimeInputContract
from engines.market_regime_engine import MarketRegimeEngine


class ContractedMarketRegimeEngine:
    """Validate market-regime inputs before delegating to the canonical engine."""

    NAME = MarketRegimeEngine.NAME

    def __init__(self, engine: MarketRegimeEngine | None = None,
                 input_contract: MarketRegimeInputContract | None = None) -> None:
        self.engine = engine or MarketRegimeEngine()
        self.input_contract = input_contract or MarketRegimeInputContract()

    def evaluate(self, stock: dict[str, Any]):
        report = self.input_contract.validate(stock)
        if not report.ready:
            result = self.engine.evaluate(stock)
            result.passed = False
            result.score = 0.0
            result.confidence = 0.0
            result.grade = "N/A"
            result.warnings = list(result.warnings or []) + ["Market regime input contract failed"]
            result.metrics = dict(result.metrics or {})
            result.metrics["input_contract"] = report.as_dict()
            return result
        result = self.engine.evaluate(stock)
        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        if report.warnings:
            result.warnings = list(result.warnings or []) + report.warnings
        return result


__all__ = ["ContractedMarketRegimeEngine"]
