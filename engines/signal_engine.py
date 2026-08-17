"""Final weighted signal generation from component engine results."""

from __future__ import annotations

from typing import Any

from config.signal_weights import SIGNAL_WEIGHTS
from engines.base_engine import BaseEngine, EngineResult
from models.signal import Signal


class SignalEngine(BaseEngine):
    NAME = "Signal Engine"
    priority = 100
    mandatory = True

    def generate(self, symbol: str, market: Any, sector: Any, fundamental: Any,
                 corporate: Any, shark: Any, technical: Any,
                 price_action: Any, risk: Any) -> Signal:
        engines = (market, sector, fundamental, corporate, shark, technical, price_action, risk)
        keys = ("market", "sector", "fundamental", "corporate", "big_shark", "technical", "price_action", "risk")
        score = sum(float(getattr(engine, "score", 0) or 0) * float(SIGNAL_WEIGHTS.get(key, 0))
                    for engine, key in zip(engines, keys))
        confidences = [float(getattr(engine, "confidence", 0) or 0) for engine in engines]
        confidence = sum(confidences) / len(confidences) if confidences else 0.0

        entry = self._value(price_action, "entry", 0.0)
        if not entry:
            entry = self._value(price_action, "close", 0.0)

        return Signal(
            symbol=symbol,
            signal=self._classify(score),
            confidence=round(confidence, 2),
            overall_score=round(score, 2),
            entry=entry,
            stoploss=self._value(risk, "stoploss"),
            target1=self._value(risk, "target1"),
            target2=self._value(risk, "target2"),
            target3=self._value(risk, "target3"),
            risk_reward=self._value(risk, "rr", self._metric(risk, "rr")),
            quantity=int(self._value(risk, "quantity", self._metric(risk, "quantity", 0)) or 0),
            reasons=self._reasons(*engines),
            warnings=self._warnings(risk),
        )

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        return EngineResult(
            engine=self.NAME,
            passed=False,
            score=0.0,
            confidence=0.0,
            grade="D",
            warnings=["Use generate() with the component engine results to create a final signal."],
        )

    @staticmethod
    def _metric(engine: Any, key: str, default: Any = 0) -> Any:
        metrics = getattr(engine, "metrics", None)
        if isinstance(metrics, dict):
            return metrics.get(key, default)
        return default

    @classmethod
    def _value(cls, engine: Any, key: str, default: Any = 0.0) -> float:
        value = getattr(engine, key, None)
        if value is None:
            value = cls._metric(engine, key, default)
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return float(default or 0)

    @staticmethod
    def _warnings(engine: Any) -> list[str]:
        return list(getattr(engine, "warnings", []) or [])

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 95: return "STRONG BUY"
        if score >= 90: return "BUY"
        if score >= 85: return "ACCUMULATE"
        if score >= 75: return "WATCHLIST"
        if score >= 60: return "HOLD"
        if score >= 40: return "REDUCE"
        return "SELL"

    @staticmethod
    def _reasons(*engines: Any) -> list[str]:
        return list(dict.fromkeys(
            reason
            for engine in engines
            for reason in (getattr(engine, "reasons", []) or [])
        ))[:20]


__all__ = ["SignalEngine"]
