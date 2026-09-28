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

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        return self.engine.evaluate(stock)

    def __getattr__(self, name: str):
        return getattr(self.engine, name)


__all__ = ["ContractedSignalEngine"]
