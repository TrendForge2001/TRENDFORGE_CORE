"""Final weighted signal generation from component engine results."""
from __future__ import annotations

from typing import Any, Mapping

from config.signal_weights import SIGNAL_WEIGHTS
from engines.base_engine import BaseEngine, EngineResult
from models.signal import Signal


class SignalEngine(BaseEngine):
    NAME = "Signal Engine"
    priority = 100
    mandatory = True

    ALIASES = {
        "Market Regime Engine": "market",
        "Sector Engine": "sector",
        "Fundamental Engine": "fundamental",
        "Corporate Action Engine": "corporate",
        "Big Shark Engine": "big_shark",
        "Technical Engine": "technical",
        "Price Action Engine": "price_action",
        "Risk Engine": "risk",
    }

    def generate_from_results(self, symbol: str, results: Mapping[str, EngineResult]) -> Signal:
        available = []
        for name, result in (results or {}).items():
            key = self.ALIASES.get(name)
            if key and isinstance(result, EngineResult) and result.max_score > 0:
                weight = float(SIGNAL_WEIGHTS.get(key, 0.0))
                if weight > 0:
                    available.append((key, result, weight))

        weight_total = sum(weight for _, _, weight in available)
        score = 0.0
        confidences = []
        for _, result, weight in available:
            normalized = max(0.0, min(100.0, result.score / result.max_score * 100.0))
            score += normalized * (weight / weight_total) if weight_total else 0.0
            confidences.append(max(0.0, min(100.0, float(result.confidence or 0))))

        risk = next((r for k, r, _ in available if k == "risk"), None)
        price_action = next((r for k, r, _ in available if k == "price_action"), None)
        confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # A failed risk engine must not silently produce an actionable signal.
        if risk is not None and not risk.passed:
            score = min(score, 59.99)

        entry = self._value(price_action, "entry", 0.0)
        if not entry:
            entry = self._value(price_action, "close", 0.0)
        if not entry:
            entry = self._value(risk, "entry", 0.0)

        return Signal(
            symbol=str(symbol or "").upper(),
            signal=self._classify(score),
            confidence=round(confidence, 2),
            overall_score=round(score, 2),
            entry=entry,
            stoploss=self._value(risk, "stoploss"),
            target1=self._value(risk, "target1"),
            target2=self._value(risk, "target2"),
            target3=self._value(risk, "target3"),
            risk_reward=self._value(risk, "rr"),
            quantity=int(self._value(risk, "quantity", 0) or 0),
            reasons=self._reasons(*(r for _, r, _ in available)),
            warnings=self._warnings(*(r for _, r, _ in available)),
        )

    def generate(self, symbol: str, market: Any, sector: Any, fundamental: Any,
                 corporate: Any, shark: Any, technical: Any,
                 price_action: Any, risk: Any) -> Signal:
        return self.generate_from_results(symbol, {
            "Market Regime Engine": market,
            "Sector Engine": sector,
            "Fundamental Engine": fundamental,
            "Corporate Action Engine": corporate,
            "Big Shark Engine": shark,
            "Technical Engine": technical,
            "Price Action Engine": price_action,
            "Risk Engine": risk,
        })

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        return EngineResult(
            engine=self.NAME, passed=False, score=0.0, confidence=0.0,
            grade="D", warnings=["Use generate_from_results() to create a final signal."],
        )

    @staticmethod
    def _metric(engine: Any, key: str, default: Any = 0) -> Any:
        metrics = getattr(engine, "metrics", None) if engine is not None else None
        return metrics.get(key, default) if isinstance(metrics, dict) else default

    @classmethod
    def _value(cls, engine: Any, key: str, default: Any = 0.0) -> float:
        try:
            return float(cls._metric(engine, key, default) or 0)
        except (TypeError, ValueError):
            return float(default or 0)

    @staticmethod
    def _warnings(*engines: Any) -> list[str]:
        return list(dict.fromkeys(
            warning for engine in engines
            for warning in (getattr(engine, "warnings", []) or [])
        ))[:20]

    @staticmethod
    def _reasons(*engines: Any) -> list[str]:
        return list(dict.fromkeys(
            reason for engine in engines
            for reason in (getattr(engine, "reasons", []) or [])
        ))[:30]

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 95: return "STRONG BUY"
        if score >= 90: return "BUY"
        if score >= 85: return "ACCUMULATE"
        if score >= 75: return "WATCHLIST"
        if score >= 60: return "HOLD"
        if score >= 40: return "REDUCE"
        return "SELL"


__all__ = ["SignalEngine"]
