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
    """Run the canonical engines and assemble the final trading signal."""

    def __init__(self, engines: list[BaseEngine] | None = None) -> None:
        self.engines = engines or [
            MarketRegimeEngine(),
            SectorEngine(),
            FundamentalEngine(),
            CorporateActionEngine(),
            BigSharkEngine(),
            TechnicalEngine(),
            PriceActionEngine(),
            RiskEngine(),
        ]
        self.signal_engine = SignalEngine()

    def evaluate(self, stock: dict[str, Any]) -> dict[str, Any]:
        results: dict[str, EngineResult] = {}
        for engine in self.engines:
            try:
                result = engine.evaluate(stock)
            except Exception as exc:
                result = EngineResult(
                    engine=engine.__class__.__name__,
                    passed=False,
                    score=0.0,
                    max_score=100.0,
                    confidence=0.0,
                    grade="ERROR",
                    warnings=[str(exc)],
                )
            results[result.engine] = result

        total_max = sum(result.max_score for result in results.values())
        total_score = sum(result.score for result in results.values())
        confidence = round((total_score / total_max) * 100, 2) if total_max else 0.0

        mandatory = [e for e in self.engines if getattr(e, "mandatory", False)]
        passed = all(
            results[e.NAME].passed
            for e in mandatory
            if e.NAME in results
        )

        symbol = str(
            stock.get("symbol")
            or stock.get("ticker")
            or stock.get("tradingsymbol")
            or ""
        ).upper()
        signal = self.signal_engine.generate_from_results(symbol, results)

        # Hard-risk/event vetoes must never be overridden by a high score.
        vetoes = [
            result.engine
            for result in results.values()
            if result.metrics.get("hard_block") is True
        ]
        if vetoes and signal.signal in {"STRONG BUY", "BUY", "ACCUMULATE"}:
            signal.signal = "HOLD"
            signal.warnings.append(
                "BUY vetoed by a hard-risk event: " + ", ".join(vetoes)
            )
            passed = False

        return {
            "passed": passed,
            "score": round(total_score, 2),
            "max_score": round(total_max, 2),
            "confidence": confidence,
            "signal": signal,
            "engines": {name: result.as_dict() for name, result in results.items()},
        }

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "engines": [engine.__class__.__name__ for engine in self.engines],
            "signal_engine": self.signal_engine.NAME,
        }


__all__ = ["EngineOrchestrator"]
