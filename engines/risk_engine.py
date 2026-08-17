"""Risk engine for stop, targets, risk/reward and position sizing."""

from __future__ import annotations

from typing import Any

from engines.base_engine import BaseEngine, EngineResult
from rules.risk.atr_stop_rule import ATRStopRule
from rules.risk.position_size_rule import PositionSizeRule
from rules.risk.risk_reward_rule import RiskRewardRule
from rules.risk.volatility_rule import VolatilityRule


class RiskEngine(BaseEngine):
    NAME = "Risk Engine"
    priority = 7
    mandatory = True

    def __init__(self) -> None:
        self.atr = ATRStopRule()
        self.position = PositionSizeRule()
        self.rr = RiskRewardRule()
        self.volatility = VolatilityRule()

    @staticmethod
    def _inputs(stock: dict[str, Any]) -> tuple[Any, float]:
        snapshot = stock.get("snapshot", stock)
        capital = float(stock.get("capital", 0) or 0)
        return snapshot, capital

    def evaluate(self, stock: dict[str, Any], capital: float | None = None) -> EngineResult:
        if not isinstance(stock, dict):
            return EngineResult(self.NAME, False, 0.0, 0.0, "D", warnings=["Risk input must be a mapping."])

        snapshot, configured_capital = self._inputs(stock)
        if capital is not None:
            configured_capital = float(capital)

        close = float(getattr(snapshot, "close", 0) or 0)
        if close <= 0:
            return EngineResult(self.NAME, False, 0.0, 0.0, "D", warnings=["Positive entry price is required."])

        try:
            stop = self.atr.calculate(snapshot)
            rr = self.rr.calculate(close, stop)
            quantity = self.position.calculate(configured_capital, 1, close, stop)
            score = float(self.volatility.score(snapshot))
        except (TypeError, ValueError, AttributeError) as exc:
            return EngineResult(self.NAME, False, 0.0, 0.0, "D", warnings=[f"Risk calculation failed: {exc}"])

        risk_per_share = max(0.0, close - stop)
        target1 = close + risk_per_share
        target2 = close + 2 * risk_per_share
        target3 = close + 3 * risk_per_share
        confidence = round(min(100.0, score), 2)

        return EngineResult(
            engine=self.NAME,
            passed=score >= 60 and rr >= 2,
            score=score,
            confidence=confidence,
            grade="A+" if score >= 90 else "A" if score >= 80 else "B" if score >= 70 else "C" if score >= 60 else "D",
            reasons=["ATR based risk", "Risk/reward calculated", "Position size calculated"],
            metrics={
                "entry": close,
                "stoploss": stop,
                "target1": target1,
                "target2": target2,
                "target3": target3,
                "rr": rr,
                "quantity": quantity,
            },
        )


__all__ = ["RiskEngine"]
