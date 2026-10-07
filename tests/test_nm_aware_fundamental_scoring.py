from __future__ import annotations

from datetime import datetime, timezone

from core.database import initialize_database
from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from engines.contracted_fundamental_engine import ContractedFundamentalEngine
from engines.fundamental_contract import FundamentalInputContract
from engines.fundamental_engine import FundamentalEngine
from engines.fundamental_scoring_readiness import (
    FundamentalScoringReadiness,
    FundamentalScoringReadinessResolver,
)
from providers.sqlite_fundamental_provider import SQLiteFundamentalProvider
from reconstruction.enrichment import StockEnricher


def _numeric_stock(**overrides):
    stock = {
        "symbol": "TEST",
        "roce": 30.0,
        "roe": 20.0,
        "sales_growth": 25.0,
        "profit_growth": 25.0,
        "eps_growth": 25.0,
        "debt_equity": 0.20,
        "promoter_holding": 70.0,
        "pledged": 0.0,
    }
    stock.update(overrides)
    return stock


def _nm_evidence(reason: str = "NEGATIVE_BASE"):
    return {
        "field": "eps_growth",
        "value": None,
        "value_status": "N/M",
        "period_type": "CAGR",
        "period_label": "FY2023-FY2026",
        "period_start": "FY2023",
        "period_end": "FY2026",
        "methodology": "3Y_CAGR",
        "source_type": "SCREENER",
        "source": "Screener",
        "source_ref": "https://example.test/TEST",
        "as_of": "2026-03-31",
        "reason": reason,
    }


def _nm_stock(reason: str = "NEGATIVE_BASE", **overrides):
    stock = _numeric_stock(eps_growth=None)
    stock["fundamental_data_quality"] = {
        "stale": False,
        "missing": ["eps_growth"],
        "field_evidence": {"eps_growth": _nm_evidence(reason)},
    }
    stock.update(overrides)
    return stock


def test_numeric_ready_scoring_is_unchanged():
    result = ContractedFundamentalEngine().evaluate(_numeric_stock())

    assert result.passed is True
    assert result.score == 53.0
    assert result.max_score == 53.0
    assert result.confidence == 100.0
    assert result.grade == "A+"
    assert result.metrics["scoring_state"] == "NUMERIC_READY"
    assert result.metrics["data_confidence_pct"] == 100.0
    assert result.metrics["excluded_fields"] == []


def test_strict_contract_stays_fail_closed_for_nm_eps():
    stock = _nm_stock()

    report = FundamentalInputContract().validate(stock)

    assert report.ready is False
    assert report.missing == ["eps_growth"]


def test_valid_negative_base_nm_eps_is_evidence_complete():
    stock = _nm_stock()
    resolver = FundamentalScoringReadinessResolver()

    readiness = resolver.assess(stock)

    assert readiness.eligible is True
    assert readiness.state == FundamentalScoringReadiness.EVIDENCE_COMPLETE_NM
    assert readiness.excluded_fields == ("eps_growth",)
    assert readiness.data_confidence_pct == 87.5
    assert readiness.strict_report is not None
    assert readiness.strict_report.ready is False


def test_nm_aware_score_excludes_eps_weight_and_caps_data_confidence():
    result = ContractedFundamentalEngine().evaluate(_nm_stock())

    assert result.passed is True
    assert result.score == 47.0
    assert result.max_score == 47.0
    assert result.confidence == 87.5
    assert result.grade == "A"
    assert result.metrics["quality_score_pct"] == 100.0
    assert result.metrics["data_confidence_pct"] == 87.5
    assert result.metrics["effective_max_score"] == 47.0
    assert result.metrics["excluded_fields"] == ["eps_growth"]
    assert result.metrics["scoring_state"] == "EVIDENCE_COMPLETE_NM"
    assert result.metrics["input_contract"]["ready"] is False
    assert result.metrics["input_contract"]["missing"] == ["eps_growth"]
    assert any("EPS Growth is N/M" in item for item in result.warnings)


def test_nm_score_uses_normalized_pass_ratio_not_full_53_point_threshold():
    stock = _nm_stock(
        roce=20.0,          # 6
        roe=15.0,           # 5
        sales_growth=15.0,  # 5
        profit_growth=15.0, # 5
        debt_equity=0.5,    # 7
        promoter_holding=60.0,  # 5
        pledged=5.0,        # 4
    )
    result = ContractedFundamentalEngine().evaluate(stock)

    # 37 / 47 = 78.72%; this passes the normalized 70% threshold.
    assert result.score == 37.0
    assert result.max_score == 47.0
    assert result.metrics["minimum_score"] == 32.9
    assert result.passed is True


def test_insufficient_history_nm_remains_fail_closed():
    result = ContractedFundamentalEngine().evaluate(
        _nm_stock(reason="INSUFFICIENT_HISTORY")
    )

    assert result.passed is False
    assert result.score == 0.0
    assert result.max_score == 53.0
    assert result.confidence == 0.0
    assert result.metrics["scoring_state"] == "INCOMPLETE"
    assert any(
        "NEGATIVE_BASE or ZERO_BASE" in item
        for item in result.metrics["scoring_readiness"]["reasons"]
    )


def test_nm_with_another_missing_field_remains_fail_closed():
    stock = _nm_stock(sales_growth=None)

    result = ContractedFundamentalEngine().evaluate(stock)

    assert result.passed is False
    assert result.metrics["scoring_state"] == "INCOMPLETE"
    assert result.metrics["input_contract"]["missing"] == [
        "sales_growth",
        "eps_growth",
    ]


def test_zero_base_nm_is_scoring_eligible():
    readiness = FundamentalScoringReadinessResolver().assess(
        _nm_stock(reason="ZERO_BASE")
    )

    assert readiness.eligible is True
    assert readiness.state == "EVIDENCE_COMPLETE_NM"


def test_direct_engine_exclusion_keeps_strict_contract_visible():
    stock = _nm_stock()
    result = FundamentalEngine().evaluate_with_exclusions(
        stock,
        excluded_fields=("eps_growth",),
        data_confidence_pct=87.5,
    )

    assert result.score == 47.0
    assert result.max_score == 47.0
    assert result.metrics["input_contract"]["ready"] is False
    assert result.metrics["input_contract"]["missing"] == ["eps_growth"]


def test_sqlite_provider_and_enricher_propagate_nm_evidence_to_scoring(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    repository = FundamentalsRepository(db_path=str(db_path))
    evidence_repository = FundamentalFieldEvidenceRepository(
        db_path=str(db_path)
    )
    now = datetime.now(timezone.utc).isoformat()

    repository.save(
        {
            "symbol": "GVT&D",
            "roce": 30.0,
            "roe": 20.0,
            "sales_growth": 25.0,
            "profit_growth": 25.0,
            "eps_growth": None,
            "debt_to_equity": 0.20,
            "promoter_holding": 70.0,
            "pledged": 0.0,
            "source": "test",
            "as_of": now,
        }
    )
    evidence_repository.add_many(
        [
            {
                "symbol": "GVT&D",
                **_nm_evidence("NEGATIVE_BASE"),
            }
        ]
    )

    provider = SQLiteFundamentalProvider(
        repository=repository,
        evidence_repository=evidence_repository,
        max_age_days=365,
    )
    snapshot = provider.get("GVT&D")

    assert (
        snapshot["_meta"]["field_evidence"]["eps_growth"]["value_status"]
        == "N/M"
    )

    enricher = StockEnricher(providers={"fundamentals": provider})
    merged = enricher.merge(
        {"symbol": "GVT&D"},
        enricher.enrich({"symbol": "GVT&D"}),
    )

    assert merged.get("eps_growth") is None
    assert (
        merged["fundamental_data_quality"]["field_evidence"]["eps_growth"][
            "reason"
        ]
        == "NEGATIVE_BASE"
    )

    result = ContractedFundamentalEngine().evaluate(merged)
    assert result.passed is True
    assert result.metrics["scoring_state"] == "EVIDENCE_COMPLETE_NM"
    assert result.max_score == 47.0
    assert result.confidence == 87.5

    repository.close()
    evidence_repository.close()
