"""Final weighted signal generation from component engine results."""
from __future__ import annotations

from typing import Any, Mapping

from config.signal_weights import SIGNAL_WEIGHTS
from engines.base_engine import BaseEngine, EngineResult
from engines.trend_alignment import evaluate_trend_alignment
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

    @staticmethod
    def _clamp_pct(value: Any) -> float:
        try:
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _available_results(
        self,
        results: Mapping[str, EngineResult] | None,
    ) -> list[tuple[str, str, EngineResult, float]]:
        available: list[tuple[str, str, EngineResult, float]] = []
        for name, result in (results or {}).items():
            key = self.ALIASES.get(name)
            if key and isinstance(result, EngineResult) and result.max_score > 0:
                weight = float(SIGNAL_WEIGHTS.get(key, 0.0))
                if weight > 0:
                    available.append((name, key, result, weight))
        return available

    def explain_from_results(
        self,
        symbol: str,
        results: Mapping[str, EngineResult] | None,
    ) -> dict[str, Any]:
        """Return an arithmetic ledger for the canonical final signal score."""
        available = self._available_results(results)
        weight_total = sum(weight for _, _, _, weight in available)

        components: list[dict[str, Any]] = []
        component_total = 0.0
        confidences: list[float] = []

        for engine_name, key, result, configured_weight in available:
            normalized = self._clamp_pct(
                result.score / result.max_score * 100.0
                if result.max_score
                else 0.0
            )
            effective_weight = (
                configured_weight / weight_total
                if weight_total
                else 0.0
            )
            contribution = normalized * effective_weight
            component_total += contribution
            confidences.append(self._clamp_pct(result.confidence))

            components.append(
                {
                    "engine": engine_name,
                    "key": key,
                    "passed": bool(result.passed),
                    "score": round(float(result.score or 0.0), 4),
                    "max_score": round(float(result.max_score or 0.0), 4),
                    "normalized_score_pct": round(normalized, 4),
                    "configured_weight": round(configured_weight, 6),
                    "effective_weight": round(effective_weight, 6),
                    "contribution_points": round(contribution, 4),
                    "confidence": round(
                        self._clamp_pct(result.confidence),
                        2,
                    ),
                    "grade": result.grade,
                }
            )

        pre_adjustment_score = component_total
        score = component_total

        risk = next(
            (
                result
                for _, key, result, _ in available
                if key == "risk"
            ),
            None,
        )
        risk_cap_active = risk is not None and not risk.passed
        risk_score_before = score
        if risk_cap_active:
            score = min(score, 59.99)
        risk_score_after = score
        risk_cap_deduction = max(0.0, risk_score_before - risk_score_after)

        alignment = evaluate_trend_alignment(results)
        trend_score_before = score
        requested_penalty = max(float(alignment.penalty or 0.0), 0.0)
        score = max(0.0, score - requested_penalty)
        trend_score_after = score
        applied_penalty = max(0.0, trend_score_before - trend_score_after)

        confidence = (
            sum(confidences) / len(confidences)
            if confidences
            else 0.0
        )
        final_score = round(score, 2)
        signal_name = self._classify(score)

        return {
            "symbol": str(symbol or "").upper(),
            "scoring_mode": "canonical_weighted",
            "components": components,
            "configured_weight_total": round(
                sum(float(value) for value in SIGNAL_WEIGHTS.values()),
                6,
            ),
            "available_weight_total": round(weight_total, 6),
            "weights_renormalized": (
                bool(available)
                and abs(weight_total - 1.0) > 1e-9
            ),
            "component_total_pre_adjustment": round(
                pre_adjustment_score,
                4,
            ),
            "risk_cap": {
                "active": risk_cap_active,
                "cap": 59.99,
                "score_before": round(risk_score_before, 4),
                "score_after": round(risk_score_after, 4),
                "deduction": round(risk_cap_deduction, 4),
            },
            "trend_alignment": alignment.as_dict(),
            "trend_penalty": {
                "requested": round(requested_penalty, 4),
                "applied": round(applied_penalty, 4),
                "score_before": round(trend_score_before, 4),
                "score_after": round(trend_score_after, 4),
            },
            "final_score": final_score,
            "signal": signal_name,
            "confidence": round(confidence, 2),
            "reconciled": (
                abs(
                    final_score
                    - round(
                        max(
                            0.0,
                            min(
                                pre_adjustment_score,
                                59.99,
                            )
                            if risk_cap_active
                            else pre_adjustment_score,
                        )
                        - requested_penalty,
                        2,
                    )
                )
                < 1e-9
            ),
        }

    def generate_from_results(
        self,
        symbol: str,
        results: Mapping[str, EngineResult],
    ) -> Signal:
        explanation = self.explain_from_results(symbol, results)
        available = self._available_results(results)

        risk = next(
            (result for _, key, result, _ in available if key == "risk"),
            None,
        )
        price_action = next(
            (
                result
                for _, key, result, _ in available
                if key == "price_action"
            ),
            None,
        )
        alignment = evaluate_trend_alignment(results)

        entry = self._value(price_action, "entry", 0.0)
        if not entry:
            entry = self._value(price_action, "close", 0.0)
        if not entry:
            entry = self._value(risk, "entry", 0.0)

        reasons = self._reasons(*(r for _, _, r, _ in available))
        warnings = self._warnings(*(r for _, _, r, _ in available))
        if alignment.status == "COUNTER_TREND":
            warning = (
                f"{alignment.message} Final signal score reduced by "
                f"{alignment.penalty:g} points."
            )
            warnings = list(dict.fromkeys([*warnings, warning]))
            reasons = list(
                dict.fromkeys(
                    [
                        *reasons,
                        "Counter-trend setup penalized by regime alignment",
                    ]
                )
            )

        return Signal(
            symbol=str(symbol or "").upper(),
            signal=explanation["signal"],
            confidence=explanation["confidence"],
            overall_score=explanation["final_score"],
            entry=entry,
            stoploss=self._value(risk, "stoploss"),
            target1=self._value(risk, "target1"),
            target2=self._value(risk, "target2"),
            target3=self._value(risk, "target3"),
            risk_reward=self._value(risk, "rr"),
            quantity=int(self._value(risk, "quantity", 0) or 0),
            reasons=reasons,
            warnings=warnings,
        )

    def generate(
        self,
        symbol: str,
        market: Any,
        sector: Any,
        fundamental: Any,
        corporate: Any,
        shark: Any,
        technical: Any,
        price_action: Any,
        risk: Any,
    ) -> Signal:
        return self.generate_from_results(
            symbol,
            {
                "Market Regime Engine": market,
                "Sector Engine": sector,
                "Fundamental Engine": fundamental,
                "Corporate Action Engine": corporate,
                "Big Shark Engine": shark,
                "Technical Engine": technical,
                "Price Action Engine": price_action,
                "Risk Engine": risk,
            },
        )

    def evaluate(self, stock: dict[str, Any]) -> EngineResult:
        return EngineResult(
            engine=self.NAME,
            passed=False,
            score=0.0,
            confidence=0.0,
            grade="D",
            warnings=[
                "Use generate_from_results() to create a final signal."
            ],
        )

    @staticmethod
    def _metric(engine: Any, key: str, default: Any = 0) -> Any:
        metrics = (
            getattr(engine, "metrics", None)
            if engine is not None
            else None
        )
        return (
            metrics.get(key, default)
            if isinstance(metrics, dict)
            else default
        )

    @classmethod
    def _value(
        cls,
        engine: Any,
        key: str,
        default: Any = 0.0,
    ) -> float:
        try:
            return float(cls._metric(engine, key, default) or 0)
        except (TypeError, ValueError):
            return float(default or 0)

    @staticmethod
    def _warnings(*engines: Any) -> list[str]:
        return list(
            dict.fromkeys(
                warning
                for engine in engines
                for warning in (getattr(engine, "warnings", []) or [])
            )
        )[:20]

    @staticmethod
    def _reasons(*engines: Any) -> list[str]:
        return list(
            dict.fromkeys(
                reason
                for engine in engines
                for reason in (getattr(engine, "reasons", []) or [])
            )
        )[:30]

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 95:
            return "STRONG BUY"
        if score >= 90:
            return "BUY"
        if score >= 85:
            return "ACCUMULATE"
        if score >= 75:
            return "WATCHLIST"
        if score >= 60:
            return "HOLD"
        if score >= 40:
            return "REDUCE"
        return "SELL"


__all__ = ["SignalEngine"]
