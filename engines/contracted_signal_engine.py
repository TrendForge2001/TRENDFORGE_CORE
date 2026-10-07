"""Contract adapter for final Signal generation."""
from __future__ import annotations
from typing import Any, Mapping

from engines.base_engine import BaseEngine, EngineResult
from engines.signal_contract import SignalInputContract
from engines.signal_engine import SignalEngine


class ContractedSignalEngine(BaseEngine):
    NAME = SignalEngine.NAME
    mandatory = True
    priority = getattr(SignalEngine, "priority", 10)

    def __init__(self, engine: SignalEngine | None = None, input_contract: SignalInputContract | None = None):
        self.engine = engine or SignalEngine()
        self.input_contract = input_contract or SignalInputContract()

    def generate_from_results(self, symbol: str, results: Mapping[str, EngineResult]):
        report = self.input_contract.validate(results)
        if not report.ready:
            from models.signal import Signal
            return Signal(
                symbol=symbol,
                signal="HOLD",
                confidence=0.0,
                overall_score=0.0,
                reasons=[],
                warnings=report.warnings + report.invalid,
            )
        signal = self.engine.generate_from_results(symbol, results)
        signal.warnings = list(signal.warnings or []) + list(report.warnings)
        return signal

    def explain_from_results(
        self,
        symbol: str,
        results: Mapping[str, EngineResult],
    ) -> dict[str, Any]:
        report = self.input_contract.validate(results)
        if not report.ready:
            return {
                "symbol": str(symbol or "").upper(),
                "scoring_mode": "contract_failed",
                "components": [],
                "configured_weight_total": 1.0,
                "available_weight_total": 0.0,
                "weights_renormalized": False,
                "component_total_pre_adjustment": 0.0,
                "risk_cap": {
                    "active": False,
                    "cap": 59.99,
                    "score_before": 0.0,
                    "score_after": 0.0,
                    "deduction": 0.0,
                },
                "trend_alignment": {},
                "trend_penalty": {
                    "requested": 0.0,
                    "applied": 0.0,
                    "score_before": 0.0,
                    "score_after": 0.0,
                },
                "final_score": 0.0,
                "signal": "HOLD",
                "confidence": 0.0,
                "reconciled": True,
                "input_contract": report.as_dict(),
            }
        explanation = self.engine.explain_from_results(symbol, results)
        explanation["input_contract"] = report.as_dict()
        return explanation

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        report = self.input_contract.validate(stock)
        if not report.ready:
            return EngineResult(engine=self.NAME, passed=False, score=0.0, max_score=100.0,
                                confidence=0.0, grade="ERROR", warnings=list(report.warnings) + list(report.invalid),
                                metrics={"input_contract": report.as_dict()})
        return self.engine.evaluate(stock)

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedSignalEngine"]
