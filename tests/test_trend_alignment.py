from __future__ import annotations

from dataclasses import dataclass

from engines.base_engine import EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from engines.signal_engine import SignalEngine
from engines.trend_alignment import evaluate_trend_alignment


def engine_result(name: str, metrics: dict, *, reasons=None) -> EngineResult:
    return EngineResult(
        engine=name,
        passed=True,
        score=100.0,
        max_score=100.0,
        confidence=100.0,
        grade="A+",
        metrics=metrics,
        reasons=list(reasons or []),
    )


def counter_trend_results() -> dict[str, EngineResult]:
    return {
        "Market Regime Engine": engine_result(
            "Market Regime Engine",
            {"regime": "BEARISH"},
        ),
        "Technical Engine": engine_result(
            "Technical Engine",
            {
                "close": 90.0,
                "EMA_20": 100.0,
                "EMA_50": 110.0,
                "EMA_200": 120.0,
            },
        ),
        "Price Action Engine": engine_result(
            "Price Action Engine",
            {"direction": "BULLISH", "uptrend": True, "downtrend": False},
            reasons=["Confirmed price uptrend"],
        ),
    }


def aligned_results() -> dict[str, EngineResult]:
    return {
        "Market Regime Engine": engine_result(
            "Market Regime Engine",
            {"regime": "BULLISH"},
        ),
        "Technical Engine": engine_result(
            "Technical Engine",
            {
                "close": 130.0,
                "EMA_20": 120.0,
                "EMA_50": 110.0,
                "EMA_200": 100.0,
            },
        ),
        "Price Action Engine": engine_result(
            "Price Action Engine",
            {"direction": "BULLISH", "uptrend": True, "downtrend": False},
        ),
    }


def test_counter_trend_alignment_detects_regime_and_ema_conflicts():
    alignment = evaluate_trend_alignment(counter_trend_results())

    assert alignment.status == "COUNTER_TREND"
    assert alignment.market_regime == "BEARISH"
    assert alignment.market_bias == "BEARISH"
    assert alignment.ema_bias == "BEARISH"
    assert alignment.price_action_bias == "BULLISH"
    assert alignment.penalty == 12.0
    assert alignment.conflicts == (
        "price_action_vs_market_regime",
        "price_action_vs_ema_stack",
    )
    assert "counter-trend" in alignment.message


def test_aligned_trend_evidence_has_no_penalty():
    alignment = evaluate_trend_alignment(aligned_results())

    assert alignment.status == "ALIGNED"
    assert alignment.penalty == 0.0
    assert alignment.conflicts == ()


def test_signal_engine_applies_bounded_alignment_penalty():
    signal = SignalEngine().generate_from_results("ABC", counter_trend_results())

    assert signal.overall_score == 88.0
    assert signal.signal == "ACCUMULATE"
    assert any("reduced by 12 points" in warning for warning in signal.warnings)
    assert "Counter-trend setup penalized by regime alignment" in signal.reasons


@dataclass
class ReadyReport:
    ready: bool = True
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()

    def as_dict(self):
        return {"ready": True, "missing": [], "invalid": []}


class ReadyContract:
    def validate(self, stock):
        return ReadyReport()


class StaticEngine:
    mandatory = False

    def __init__(self, result: EngineResult):
        self.result = result
        self.NAME = result.engine

    def evaluate(self, stock):
        return self.result


def test_orchestrator_exposes_alignment_and_clarifies_price_action_horizon():
    results = counter_trend_results()
    orchestrator = EngineOrchestrator(
        engines=[StaticEngine(result) for result in results.values()],
        input_contract=ReadyContract(),
    )
    orchestrator.signal_engine = SignalEngine()

    output = orchestrator.evaluate({"symbol": "ABC"})

    assert output["trend_alignment"]["status"] == "COUNTER_TREND"
    assert output["trend_alignment"]["penalty"] == 12.0
    reasons = output["engines"]["Price Action Engine"]["reasons"]
    assert "Short-term price-structure uptrend" in reasons
    assert "Confirmed price uptrend" not in reasons
