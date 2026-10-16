from __future__ import annotations

from scanner.full_pipeline import FullScannerPipeline


def _pipeline() -> FullScannerPipeline:
    return FullScannerPipeline(provider=object())


def _signal(name: str = "HOLD", score: float = 40.0) -> dict:
    return {
        "signal": name,
        "overall_score": score,
        "confidence": 70.0,
    }


def _fundamental(
    *,
    passed: bool,
    state: str,
    missing: list[str] | None = None,
    invalid: list[str] | None = None,
    eligible: bool | None = None,
) -> dict:
    return {
        "passed": passed,
        "score": 40.0 if passed else 0.0,
        "max_score": 53.0,
        "confidence": 75.0 if passed else 0.0,
        "warnings": [],
        "metrics": {
            "scoring_state": state,
            "data_confidence_pct": 100.0 if passed else 0.0,
            "scoring_readiness": {
                "state": state,
                "eligible": passed if eligible is None else eligible,
                "excluded_fields": [],
            },
            "input_contract": {
                "ready": not (missing or invalid),
                "missing": list(missing or []),
                "invalid": list(invalid or []),
                "warnings": [],
            },
        },
    }


def test_incomplete_fundamentals_and_risk_off_are_both_explained():
    result = {
        "symbol": "CORRECT",
        "passed": False,
        "signal": _signal("HOLD", 41.25),
        "engines": {
            "Market Regime Engine": {
                "passed": False,
                "score": 25.0,
                "warnings": ["Risk-off regime"],
                "metrics": {
                    "regime": "RISK_OFF",
                    "direction": "BEARISH",
                    "score": 25.0,
                },
            },
            "Fundamental Engine": _fundamental(
                passed=False,
                state="INCOMPLETE",
                missing=["roce", "roe"],
                eligible=False,
            ),
            "Risk Engine": {
                "passed": True,
                "score": 80.0,
                "warnings": [],
                "metrics": {
                    "rr": 2.0,
                    "entry": 100.0,
                    "stoploss": 95.0,
                    "quantity": 100,
                },
            },
        },
        "failed_mandatory": [
            "Market Regime Engine",
            "Fundamental Engine",
        ],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result], top_n=20)
    row = output["analysis_top_picks"][0]

    assert output["eligibility_semantics_version"] == "R67.3"
    assert output["execution_explainability_version"] == "R69.3"
    assert row["analysis_eligible"] is True
    assert row["execution_eligible"] is False
    assert "market_regime:risk_off" in row["execution_block_reasons"]
    assert "fundamental:data_incomplete" in row["execution_block_reasons"]
    assert row["fundamental_readiness"]["status"] == "DATA_INCOMPLETE"
    assert row["fundamental_readiness"]["missing_fields"] == ["roce", "roe"]
    assert row["market_regime_context"]["risk_off"] is True
    assert row["risk_context"]["passed"] is True
    assert output["execution_top_picks"] == []


def test_numeric_ready_fundamental_failure_is_quality_not_missing_data():
    result = {
        "symbol": "QUALITYFAIL",
        "passed": False,
        "signal": _signal("HOLD", 52.0),
        "engines": {
            "Fundamental Engine": _fundamental(
                passed=False,
                state="NUMERIC_READY",
                eligible=True,
            ),
        },
        "failed_mandatory": ["Fundamental Engine"],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result])
    row = output["analysis_top_picks"][0]

    assert row["fundamental_readiness"]["status"] == "READY_FAIL_QUALITY"
    assert "fundamental:quality_failed" in row["execution_block_reasons"]
    assert "fundamental:data_incomplete" not in row["execution_block_reasons"]


def test_invalid_fundamental_values_are_distinct_from_incomplete_data():
    result = {
        "symbol": "INVALIDFUND",
        "passed": False,
        "signal": _signal(),
        "engines": {
            "Fundamental Engine": _fundamental(
                passed=False,
                state="INCOMPLETE",
                invalid=["promoter_holding"],
                eligible=False,
            ),
        },
        "failed_mandatory": ["Fundamental Engine"],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result])
    row = output["analysis_top_picks"][0]

    assert row["fundamental_readiness"]["status"] == "INVALID"
    assert "fundamental:invalid_data" in row["execution_block_reasons"]


def test_nm_ready_is_exposed_without_calling_data_incomplete():
    result = {
        "symbol": "NMQUALITY",
        "passed": False,
        "signal": _signal(),
        "engines": {
            "Fundamental Engine": {
                **_fundamental(
                    passed=False,
                    state="EVIDENCE_COMPLETE_NM",
                    eligible=True,
                ),
                "metrics": {
                    **_fundamental(
                        passed=False,
                        state="EVIDENCE_COMPLETE_NM",
                        eligible=True,
                    )["metrics"],
                    "excluded_fields": ["eps_growth"],
                    "data_confidence_pct": 87.5,
                },
            },
        },
        "failed_mandatory": ["Fundamental Engine"],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result])
    row = output["analysis_top_picks"][0]

    assert row["fundamental_readiness"]["status"] == "NM_READY"
    assert "fundamental:quality_failed_nm" in row["execution_block_reasons"]
    assert "fundamental:data_incomplete" not in row["execution_block_reasons"]


def test_risk_failure_has_specific_execution_block():
    result = {
        "symbol": "RISKFAIL",
        "passed": False,
        "signal": _signal("HOLD", 58.0),
        "engines": {
            "Risk Engine": {
                "passed": False,
                "score": 40.0,
                "warnings": [],
                "metrics": {
                    "rr": 2.0,
                    "entry": 100.0,
                    "stoploss": 95.0,
                    "quantity": 100,
                },
            },
        },
        "failed_mandatory": ["Risk Engine"],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result])
    row = output["analysis_top_picks"][0]

    assert "risk:failed" in row["execution_block_reasons"]
    assert row["risk_context"]["rr"] == 2.0
    assert row["execution_eligible"] is False


def test_batch_diagnostics_count_specific_blockers_and_readiness():
    rows = [
        {
            "symbol": "INCOMPLETE",
            "passed": False,
            "signal": _signal(),
            "engines": {
                "Fundamental Engine": _fundamental(
                    passed=False,
                    state="INCOMPLETE",
                    missing=["roce"],
                    eligible=False,
                ),
            },
            "failed_mandatory": ["Fundamental Engine"],
            "missing_mandatory": [],
            "execution_errors": [],
        },
        {
            "symbol": "RISKOFF",
            "passed": False,
            "signal": _signal(),
            "engines": {
                "Market Regime Engine": {
                    "passed": False,
                    "score": 20.0,
                    "warnings": [],
                    "metrics": {
                        "regime": "RISK_OFF",
                        "direction": "BEARISH",
                    },
                },
            },
            "failed_mandatory": ["Market Regime Engine"],
            "missing_mandatory": [],
            "execution_errors": [],
        },
    ]

    output = _pipeline()._finalize(rows)
    diagnostics = output["eligibility_diagnostics"]

    assert diagnostics["execution_block_counts"][
        "fundamental:data_incomplete"
    ] == 1
    assert diagnostics["execution_block_counts"][
        "market_regime:risk_off"
    ] == 1
    assert diagnostics["fundamental_readiness_counts"][
        "DATA_INCOMPLETE"
    ] == 1
    assert diagnostics["fundamental_readiness_counts"]["MISSING"] == 1
    assert diagnostics["market_regime_counts"]["RISK_OFF"] == 1


def test_execution_eligible_buy_has_no_execution_block():
    result = {
        "symbol": "ACTIONABLE",
        "passed": True,
        "signal": _signal("BUY", 94.0),
        "engines": {
            "Fundamental Engine": _fundamental(
                passed=True,
                state="NUMERIC_READY",
                eligible=True,
            ),
            "Market Regime Engine": {
                "passed": True,
                "score": 80.0,
                "warnings": [],
                "metrics": {
                    "regime": "RISK_ON",
                    "direction": "BULLISH",
                },
            },
            "Risk Engine": {
                "passed": True,
                "score": 80.0,
                "warnings": [],
                "metrics": {
                    "rr": 2.0,
                    "entry": 100.0,
                    "stoploss": 95.0,
                    "quantity": 100,
                },
            },
        },
        "failed_mandatory": [],
        "missing_mandatory": [],
        "execution_errors": [],
    }

    output = _pipeline()._finalize([result])
    row = output["execution_top_picks"][0]

    assert row["execution_eligible"] is True
    assert row["execution_block_reasons"] == []
    assert row["primary_execution_block"] is None
    assert row["fundamental_readiness"]["status"] == "READY_PASS"
