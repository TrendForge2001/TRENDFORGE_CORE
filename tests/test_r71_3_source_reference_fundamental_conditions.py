"""R71.3 source-Excel research priorities must remain read-only diagnostics."""
from __future__ import annotations

from config.reference_fundamental_conditions import (
    AGGRESSIVE, CONSERVATIVE, REFERENCE_BOOKS, SECTOR_OBSERVATIONS,
    SELECTION_REFERENCE_COLUMNS, reference_observation_coverage,
    reference_priority_rows,
)
from engines.contracted_fundamental_engine import ContractedFundamentalEngine
from engines.fundamental_engine import FundamentalEngine


def test_source_profile_priority_order_and_no_fabricated_cutoffs():
    assert REFERENCE_BOOKS == (
        "Equity research-1.xlsx", "Stock selection 10 oct 26.xlsx"
    )
    assert len(AGGRESSIVE) == 18
    assert len(CONSERVATIVE) == 17
    assert [key for key, _ in AGGRESSIVE[:6]] == [
        "operating_profit_margin", "peg", "roe_3y_avg",
        "roce_3y_avg", "sales_growth_3y", "eps_growth_3y",
    ]
    assert [key for key, _ in CONSERVATIVE[:7]] == [
        "debt_equity", "interest_coverage", "quick_ratio",
        "current_ratio", "promoter_holding", "pledged",
        "promoter_holding_change",
    ]
    for profile in ("aggressive", "conservative"):
        rows = reference_priority_rows(profile)
        assert [row["priority"] for row in rows] == list(range(1, len(rows) + 1))
        assert all(row["numeric_cutoff"] is None for row in rows)
        assert all(row["points"] is None for row in rows)
        assert all(row["scoring_status"] == "reference_only_unconfigured" for row in rows)


def test_source_excel_historical_values_not_embedded():
    keys = dict(SELECTION_REFERENCE_COLUMNS)
    assert keys["Sales Var 5Yrs %"] == "sales_growth_5y"
    assert keys["ROCE 5Yr %"] == "roce_5y_avg"
    assert keys["ROE 5Yr %"] == "roe_5y_avg"
    assert "casa_ratio" in SECTOR_OBSERVATIONS["bank"]
    assert "inventory_turnover" in SECTOR_OBSERVATIONS["pharma"]


def test_coverage_never_substitutes_mismatched_periods():
    observed = {
        "roe": 20.0, "roce": 24.0, "eps_growth": 22,
        "sales_growth": 18, "profit_growth": 15,
        "promoter_holding": 61.0, "debt_equity": 0.3,
        "pledged": 0.0,
    }
    agg = reference_observation_coverage(observed, "AGGRESSIVE")
    con = reference_observation_coverage(observed, "conservative")
    assert agg["available_count"] == 3  # profit growth, promoter, debt/equity
    assert con["available_count"] == 4  # debt/equity, promoter, pledge, profit growth
    assert "roe_3y_avg" in agg["missing_fields"]
    assert "roce_3y_avg" in con["missing_fields"]
    assert "sales_growth_3y" in con["missing_fields"]
    assert agg["quality_score"] is None and con["pass"] is None
    assert agg["affects_execution_eligibility"] is False


def test_nonfinite_data_never_counts_as_verified_observation():
    result = reference_observation_coverage({
        "debt_equity": float("nan"),
        "promoter_holding": float("inf"),
        "pledged": True,
        "interest_coverage": "not available",
        "profit_growth": "10.3",
    }, "conservative")
    assert result["available_fields"] == ["profit_growth"]
    assert result["available_count"] == 1


def test_canonical_engine_score_and_mandatory_gate_unchanged():
    values = {
        "roce": 34.0, "roe": 22.0, "sales_growth": 26.0,
        "profit_growth": 28.0, "eps_growth": 27.0, "debt_equity": 0.2,
        "promoter_holding": 73.0, "pledged": 0.0,
    }
    baseline = FundamentalEngine().evaluate(values)
    new = ContractedFundamentalEngine().evaluate(values)
    assert new.score == baseline.score
    assert new.max_score == baseline.max_score
    assert new.passed == baseline.passed
    assert new.confidence == baseline.confidence
    assert new.metrics["source_reference_profiles"]["aggressive"]["pass"] is None
    assert new.metrics["source_reference_profiles"]["conservative"]["quality_score"] is None

    incomplete = {key: value for key, value in values.items() if key != "roe"}
    rejected = ContractedFundamentalEngine().evaluate(incomplete)
    assert rejected.passed is False
    assert rejected.score == 0
    assert rejected.metrics["source_reference_profiles"]["aggressive"]["pass"] is None
