"""Contract adapter for the canonical Fundamental Engine."""
from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.fundamental_contract import FundamentalInputContract
from engines.fundamental_engine import FundamentalEngine
from engines.fundamental_scoring_readiness import (
    FundamentalScoringReadiness,
    FundamentalScoringReadinessResolver,
)


class ContractedFundamentalEngine(BaseEngine):
    NAME = FundamentalEngine.NAME
    mandatory = True
    priority = getattr(FundamentalEngine, "priority", 4)

    def __init__(
        self,
        engine: FundamentalEngine | None = None,
        input_contract: FundamentalInputContract | None = None,
        readiness_resolver: FundamentalScoringReadinessResolver | None = None,
    ):
        self.engine = engine or FundamentalEngine()
        self.input_contract = input_contract or FundamentalInputContract()
        self.readiness_resolver = (
            readiness_resolver
            or FundamentalScoringReadinessResolver(self.input_contract)
        )

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)

        if not report.ready:
            readiness = self.readiness_resolver.assess(
                stock,
                strict_report=report,
            )
            if not readiness.eligible:
                return EngineResult(
                    engine=self.NAME,
                    passed=False,
                    score=0.0,
                    max_score=self.engine.MAX_SCORE,
                    confidence=0.0,
                    grade="N/A",
                    reasons=[],
                    warnings=["Fundamental input contract failed"]
                    + list(readiness.reasons)
                    + list(report.warnings),
                    metrics={
                        "input_contract": report.as_dict(),
                        "scoring_readiness": readiness.as_dict(),
                        "scoring_state": readiness.state,
                        "data_confidence_pct": readiness.data_confidence_pct,
                    },
                )
        else:
            readiness = self.readiness_resolver.assess(
                stock,
                strict_report=report,
            )

        if readiness.state == FundamentalScoringReadiness.NUMERIC_READY:
            result = self.engine.evaluate(stock)
        else:
            result = self.engine.evaluate_with_exclusions(
                stock,
                excluded_fields=readiness.excluded_fields,
                data_confidence_pct=readiness.data_confidence_pct,
            )

        result.metrics = dict(result.metrics or {})
        result.metrics["input_contract"] = report.as_dict()
        result.metrics["scoring_readiness"] = readiness.as_dict()
        result.metrics["scoring_state"] = readiness.state
        result.metrics["data_confidence_pct"] = readiness.data_confidence_pct

        warnings = list(result.warnings or []) + list(report.warnings)
        if readiness.state == FundamentalScoringReadiness.EVIDENCE_COMPLETE_NM:
            warnings.append(
                "Fundamental score normalized across meaningful metrics; "
                "EPS Growth is N/M"
            )
        result.warnings = list(dict.fromkeys(warnings))
        return result

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedFundamentalEngine"]
