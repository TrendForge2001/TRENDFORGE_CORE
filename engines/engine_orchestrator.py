"""Canonical TrendForge analysis pipeline."""
from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from engines.big_shark_engine import BigSharkEngine
from engines.corporate_action_engine import CorporateActionEngine
from engines.fundamental_engine import FundamentalEngine
from engines.market_regime_engine import MarketRegimeEngine
from engines.price_action_engine import PriceActionEngine
from engines.risk_engine import RiskEngine
from engines.sector_engine import SectorEngine
from engines.signal_engine import SignalEngine
from engines.technical_engine import TechnicalEngine


class EngineOrchestrator:
    """Run the canonical engines and assemble one final trading evaluation."""

    def __init__(self, engines: list[BaseEngine] | None = None) -> None:
        self.engines = engines or [
            MarketRegimeEngine(), SectorEngine(), FundamentalEngine(),
            CorporateActionEngine(), BigSharkEngine(), TechnicalEngine(),
            PriceActionEngine(), RiskEngine(),
        ]
        self.signal_engine = SignalEngine()

    @staticmethod
    def _engine_name(engine: BaseEngine) -> str:
        return str(getattr(engine, "NAME", engine.__class__.__name__))

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        results: dict[str, EngineResult] = {}
        for engine in self.engines:
            name = self._engine_name(engine)
            try:
                result = engine.evaluate(stock)
                if not isinstance(result, EngineResult):
                    raise TypeError(f"{name} returned {type(result).__name__}, expected EngineResult")
            except Exception as exc:
                result = EngineResult(
                    engine=name, passed=False, score=0.0, max_score=100.0,
                    confidence=0.0, grade="ERROR",
                    warnings=[f"engine_exception:{exc}"],
                )
            results[result.engine or name] = result

        total_max = sum(max(0.0, float(r.max_score or 0.0)) for r in results.values())
        total_score = sum(float(r.score or 0.0) for r in results.values())
        confidence = round((total_score / total_max) * 100, 2) if total_max else 0.0

        mandatory = [e for e in self.engines if bool(getattr(e, "mandatory", False))]
        mandatory_failures = [
            self._engine_name(e) for e in mandatory
            if not results.get(self._engine_name(e), EngineResult(
                engine=self._engine_name(e), passed=False, score=0, confidence=0, grade="MISSING"
            )).passed
        ]
        passed = not mandatory_failures

        symbol = str(
            stock.get("symbol") or stock.get("ticker") or stock.get("tradingsymbol") or ""
        ).upper()
        signal = self.signal_engine.generate_from_results(symbol, results)

        vetoes = [
            result.engine for result in results.values()
            if result.metrics.get("hard_block") is True
        ]
        if vetoes and signal.signal in {"STRONG BUY", "BUY", "ACCUMULATE"}:
            signal.signal = "HOLD"
            signal.warnings.append("BUY vetoed by a hard-risk event: " + ", ".join(vetoes))
            passed = False

        return {
            "passed": passed,
            "mandatory_failures": mandatory_failures,
            "score": round(total_score, 2),
            "max_score": round(total_max, 2),
            "confidence": confidence,
            "signal": signal,
            "engines": {name: result.as_dict() for name, result in results.items()},
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "engine_count": len(self.engines),
            "engines": [self._engine_name(engine) for engine in self.engines],
            "signal_engine": getattr(self.signal_engine, "NAME", self.signal_engine.__class__.__name__),
        }


__all__ = ["EngineOrchestrator"]
