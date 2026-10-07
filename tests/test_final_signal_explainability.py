from __future__ import annotations

from dataclasses import dataclass

from engines.base_engine import BaseEngine, EngineResult
from engines.engine_orchestrator import EngineOrchestrator
from engines.signal_engine import SignalEngine
from models.signal import Signal
from scanner.full_pipeline import FullScannerPipeline


def _result(
    name: str,
    score: float,
    *,
    max_score: float = 100.0,
    confidence: float | None = None,
    passed: bool = True,
    metrics: dict | None = None,
) -> EngineResult:
    return EngineResult(
        engine=name,
        passed=passed,
        score=score,
        max_score=max_score,
        confidence=score if confidence is None else confidence,
        grade="A",
        metrics=dict(metrics or {}),
    )


def _canonical_results(
    *,
    market: EngineResult | None = None,
    sector: EngineResult | None = None,
    fundamental: EngineResult | None = None,
    corporate: EngineResult | None = None,
    big_shark: EngineResult | None = None,
    technical: EngineResult | None = None,
    price_action: EngineResult | None = None,
    risk: EngineResult | None = None,
) -> dict[str, EngineResult]:
    return {
        "Market Regime Engine": market
        or _result("Market Regime Engine", 100.0),
        "Sector Engine": sector
        or _result("Sector Engine", 100.0),
        "Fundamental Engine": fundamental
        or _result("Fundamental Engine", 100.0),
        "Corporate Action Engine": corporate
        or _result("Corporate Action Engine", 100.0),
        "Big Shark Engine": big_shark
        or _result("Big Shark Engine", 100.0),
        "Technical Engine": technical
        or _result("Technical Engine", 100.0),
        "Price Action Engine": price_action
        or _result("Price Action Engine", 100.0),
        "Risk Engine": risk
        or _result("Risk Engine", 100.0),
    }


def test_signal_contribution_ledger_reconciles_weighted_score():
    results = _canonical_results(
        market=_result("Market Regime Engine", 80.0),
        sector=_result("Sector Engine", 70.0),
        fundamental=_result(
            "Fundamental Engine",
            45.0,
            max_score=47.0,
            confidence=87.5,
        ),
        corporate=_result("Corporate Action Engine", 60.0),
        big_shark=_result("Big Shark Engine", 50.0),
        technical=_result("Technical Engine", 90.0),
        price_action=_result("Price Action Engine", 80.0),
        risk=_result("Risk Engine", 100.0),
    )

    engine = SignalEngine()
    explanation = engine.explain_from_results("TEST", results)
    signal = engine.generate_from_results("TEST", results)

    components = {
        item["engine"]: item
        for item in explanation["components"]
    }

    assert explanation["available_weight_total"] == 1.0
    assert explanation["weights_renormalized"] is False
    assert components["Market Regime Engine"]["contribution_points"] == 8.0
    assert components["Sector Engine"]["contribution_points"] == 7.0
    assert components["Fundamental Engine"]["normalized_score_pct"] == 95.7447
    assert components["Fundamental Engine"]["contribution_points"] == 19.1489
    assert components["Corporate Action Engine"]["contribution_points"] == 6.0
    assert components["Big Shark Engine"]["contribution_points"] == 7.5
    assert components["Technical Engine"]["contribution_points"] == 18.0
    assert components["Price Action Engine"]["contribution_points"] == 8.0
    assert components["Risk Engine"]["contribution_points"] == 5.0

    assert explanation["component_total_pre_adjustment"] == 78.6489
    assert explanation["risk_cap"]["active"] is False
    assert explanation["trend_penalty"]["applied"] == 0.0
    assert explanation["final_score"] == 78.65
    assert explanation["signal"] == "WATCHLIST"
    assert explanation["reconciled"] is True

    assert signal.overall_score == 78.65
    assert signal.signal == "WATCHLIST"


def test_signal_explanation_records_failed_risk_cap():
    results = _canonical_results(
        risk=_result(
            "Risk Engine",
            100.0,
            passed=False,
            confidence=100.0,
        )
    )

    explanation = SignalEngine().explain_from_results("TEST", results)

    assert explanation["component_total_pre_adjustment"] == 100.0
    assert explanation["risk_cap"]["active"] is True
    assert explanation["risk_cap"]["cap"] == 59.99
    assert explanation["risk_cap"]["score_before"] == 100.0
    assert explanation["risk_cap"]["score_after"] == 59.99
    assert explanation["risk_cap"]["deduction"] == 40.01
    assert explanation["final_score"] == 59.99
    assert explanation["signal"] == "REDUCE"
    assert explanation["reconciled"] is True


def test_signal_explanation_records_counter_trend_penalty():
    results = _canonical_results(
        market=_result(
            "Market Regime Engine",
            100.0,
            metrics={"regime": "BEARISH"},
        ),
        technical=_result(
            "Technical Engine",
            100.0,
            metrics={
                "close": 90.0,
                "EMA_20": 100.0,
                "EMA_50": 110.0,
                "EMA_200": 120.0,
            },
        ),
        price_action=_result(
            "Price Action Engine",
            100.0,
            metrics={"direction": "BULLISH"},
        ),
    )

    explanation = SignalEngine().explain_from_results("TEST", results)

    assert explanation["component_total_pre_adjustment"] == 100.0
    assert explanation["trend_alignment"]["status"] == "COUNTER_TREND"
    assert explanation["trend_penalty"]["requested"] == 12.0
    assert explanation["trend_penalty"]["applied"] == 12.0
    assert explanation["trend_penalty"]["score_before"] == 100.0
    assert explanation["trend_penalty"]["score_after"] == 88.0
    assert explanation["final_score"] == 88.0
    assert explanation["signal"] == "ACCUMULATE"
    assert explanation["reconciled"] is True


@dataclass
class _ReadyReport:
    ready: bool = True
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()

    def as_dict(self):
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "invalid": list(self.invalid),
        }


class _ReadyContract:
    def validate(self, stock):
        return _ReadyReport()


class _StaticEngine(BaseEngine):
    mandatory = False

    def __init__(self, result: EngineResult):
        self.result = result
        self.NAME = result.engine

    def evaluate(self, stock):
        return self.result


def test_orchestrator_explains_hard_risk_signal_override():
    results = _canonical_results(
        risk=_result(
            "Risk Engine",
            100.0,
            metrics={"hard_block": True},
        )
    )
    orchestrator = EngineOrchestrator(
        engines=[
            _StaticEngine(result)
            for result in results.values()
        ],
        input_contract=_ReadyContract(),
    )
    orchestrator.signal_engine = SignalEngine()

    output = orchestrator.evaluate({"symbol": "TEST"})
    explanation = output["signal_explainability"]

    assert output["signal"].overall_score == 100.0
    assert output["signal"].signal == "HOLD"
    assert output["passed"] is False

    assert explanation["final_score"] == 100.0
    assert explanation["final_signal"] == "HOLD"
    assert explanation["orchestrator_passed"] is False
    assert explanation["hard_risk_vetoes"] == ["Risk Engine"]
    assert explanation["reconciled"] is True
    assert explanation["orchestrator_overrides"] == [
        {
            "type": "hard_risk_veto",
            "from_signal": "STRONG BUY",
            "to_signal": "HOLD",
            "engines": ["Risk Engine"],
        }
    ]


def test_scanner_decision_explainability_describes_negative_signal_rejection():
    result = {
        "passed": True,
        "signal": Signal(
            symbol="TEST",
            signal="REDUCE",
            confidence=40.19,
            overall_score=47.85,
        ),
        "engines": {},
        "execution_errors": [],
        "missing_mandatory": [],
        "failed_mandatory": [],
        "signal_explainability": {
            "components": [
                {
                    "engine": "Fundamental Engine",
                    "contribution_points": 19.15,
                }
            ],
            "component_total_pre_adjustment": 47.85,
            "available_weight_total": 1.0,
            "weights_renormalized": False,
            "risk_cap": {"active": False},
            "trend_penalty": {"applied": 0.0},
            "trend_alignment": {"status": "INSUFFICIENT"},
            "orchestrator_overrides": [],
            "reconciled": True,
        },
    }

    explanation = FullScannerPipeline._decision_explainability(result)

    assert explanation["status"] == "REJECTED"
    assert explanation["eligible"] is False
    assert explanation["signal"] == "REDUCE"
    assert explanation["final_score"] == 47.85
    assert explanation["primary_rejection_reason"] == "negative_signal:reduce"
    assert explanation["rejection_reasons"] == ["negative_signal:reduce"]
    assert explanation["contributions"][0]["engine"] == "Fundamental Engine"
    assert explanation["score_reconciled"] is True
    assert (
        explanation["reason_messages"]
        == [
            "Final signal REDUCE is not eligible for actionable scanner ranking."
        ]
    )
    assert explanation["summary"].startswith("Rejected:")
