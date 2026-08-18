"""Canonical TrendForge analysis pipeline."""

from __future__ import annotations
from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.contracted_big_shark_engine import ContractedBigSharkEngine
from engines.contracted_market_regime_engine import ContractedMarketRegimeEngine
from engines.contracted_sector_engine import ContractedSectorEngine
from engines.contracted_technical_engine import ContractedTechnicalEngine
from engines.contracted_price_action_engine import ContractedPriceActionEngine
from engines.contracted_risk_engine import ContractedRiskEngine
from engines.corporate_action_engine import CorporateActionEngine
from engines.fundamental_engine import FundamentalEngine
from engines.input_contract import EngineInputContract
from engines.signal_engine import SignalEngine


class EngineOrchestrator(BaseEngine):
    """Run canonical engines behind a fail-closed structural input boundary."""
    NAME = "Engine Orchestrator"

    def __init__(self, engines: list[BaseEngine] | None = None, input_contract: EngineInputContract | None = None) -> None:
        self.engines = engines or [
            ContractedMarketRegimeEngine(), ContractedSectorEngine(), FundamentalEngine(),
            CorporateActionEngine(), ContractedBigSharkEngine(), ContractedTechnicalEngine(),
            ContractedPriceActionEngine(), ContractedRiskEngine(),
        ]
        self.signal_engine = SignalEngine()
        self.input_contract = input_contract or EngineInputContract()

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        report = self.input_contract.validate(stock)
        symbol = str(stock.get("symbol") or stock.get("ticker") or stock.get("tradingsymbol") or "").upper()
        if not report.ready:
            return {"passed": False, "score": 0.0, "max_score": 0.0, "confidence": 0.0,
                    "signal": self.signal_engine.generate_from_results(symbol, {}), "engines": {},
                    "input_contract": report.as_dict()}
        results: dict[str, EngineResult] = {}
        for engine in self.engines:
            try:
                result = engine.evaluate(stock)
            except Exception as exc:
                result = EngineResult(engine=engine.__class__.__name__, passed=False, score=0.0, max_score=100.0,
                                      confidence=0.0, grade="ERROR", warnings=[str(exc)])
            results[result.engine] = result
        total_max = sum(r.max_score for r in results.values())
        total_score = sum(r.score for r in results.values())
        confidence = round((total_score / total_max) * 100, 2) if total_max else 0.0
        mandatory = [e for e in self.engines if getattr(e, "mandatory", False)]
        passed = all(results[e.NAME].passed for e in mandatory if e.NAME in results)
        signal = self.signal_engine.generate_from_results(symbol, results)
        vetoes = [r.engine for r in results.values() if r.metrics.get("hard_block") is True]
        if vetoes and signal.signal in {"STRONG BUY", "BUY", "ACCUMULATE"}:
            signal.signal = "HOLD"
            signal.warnings.append("BUY vetoed by a hard-risk event: " + ", ".join(vetoes))
            passed = False
        return {"passed": passed, "score": round(total_score, 2), "max_score": round(total_max, 2),
                "confidence": confidence, "signal": signal,
                "engines": {name: result.as_dict() for name, result in results.items()},
                "input_contract": report.as_dict()}

    def health(self) -> dict[str, Any]:
        return {"status": "healthy", "engines": [e.__class__.__name__ for e in self.engines],
                "input_contract": self.input_contract.__class__.__name__,
                "engines_count": len(self.engines)}


__all__ = ["EngineOrchestrator"]
