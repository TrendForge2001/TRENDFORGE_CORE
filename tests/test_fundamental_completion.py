from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pandas as pd

from core.database import database_health, initialize_database
from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamental_field_update_repository import (
    FundamentalFieldUpdateRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from services.fundamental_completion_service import FundamentalCompletionService
from services.fundamental_data_manager import FundamentalDataManager


def _seed_half_complete(manager: FundamentalDataManager, symbol: str = "LUPIN"):
    old = datetime.now(timezone.utc) - timedelta(days=90)
    return manager.upsert(
        symbol,
        {
            "roce": 30.32,
            "sales_growth": 18.88,
            "profit_growth": 141.27,
            "debt_equity": 0.29,
        },
        source="legacy_partial_seed",
        as_of=old.isoformat(),
    )


def _standardized_completion_row(symbol: str = "LUPIN") -> dict:
    return {
        "Symbol": symbol,
        "ROCE": 999.0,
        "ROE": 18.5,
        "EPS Growth": 22.0,
        "Promoter Holding": 47.2,
        "Pledged %": 0.0,
        "Completion Source": "screener",
        "Completion Source Ref": "https://example.test/fundamentals",
        "Completion As Of": "2026-03-31",
        "ROE Period": "FY2026",
        "EPS Growth Status": "VALID",
        "EPS Growth Method": "3Y_CAGR",
        "EPS Start Period": "FY2023",
        "EPS End Period": "FY2026",
        "Promoter Holding As Of": "2026-06-30",
        "Pledged As Of": "2026-06-30",
    }


def _completion_frame(symbol: str = "LUPIN") -> pd.DataFrame:
    return pd.DataFrame([_standardized_completion_row(symbol)])


def test_database_initialization_includes_standardized_evidence_table(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    health = database_health(str(db_path))

    assert health["status"] == "ready"
    assert health["tables"] >= 15


def test_completion_export_contains_standardized_metadata_columns(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=200)
    _seed_half_complete(manager, "LUPIN")
    _seed_half_complete(manager, "BSE")

    service = FundamentalCompletionService(manager=manager)
    frame = service.completion_frame()

    assert list(frame["Symbol"]) == ["BSE", "LUPIN"]
    for column in (
        "ROE",
        "EPS Growth",
        "Promoter Holding",
        "Pledged %",
        "Completion Source",
        "Completion Source Ref",
        "Completion As Of",
        "ROE Period",
        "EPS Growth Status",
        "EPS Growth Method",
        "EPS Start Period",
        "EPS End Period",
        "EPS Growth Reason",
        "Promoter Holding As Of",
        "Pledged As Of",
    ):
        assert column in frame.columns
    assert frame["ROE"].isna().all()
    assert frame["EPS Growth"].isna().all()
    assert set(frame["Current Completeness %"]) == {50.0}
    assert set(frame["Baseline Source"]) == {"legacy_partial_seed"}


def test_completion_xlsx_has_completion_and_instructions_sheets(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)

    payload = FundamentalCompletionService(manager=manager).completion_xlsx()
    book = pd.ExcelFile(BytesIO(payload))

    assert book.sheet_names == ["Completion", "Instructions"]
    frame = pd.read_excel(BytesIO(payload), sheet_name="Completion")
    assert len(frame) == 1
    assert frame.iloc[0]["Symbol"] == "LUPIN"
    assert "ROE Period" in frame.columns
    assert "EPS Growth Method" in frame.columns


def test_completion_preview_never_writes_and_reports_ready_after(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)
    _seed_half_complete(manager)
    audit = FundamentalFieldUpdateRepository(db_path=str(db_path))
    evidence = FundamentalFieldEvidenceRepository(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        audit_repository=audit,
        evidence_repository=evidence,
    )

    completion = tmp_path / "completion.xlsx"
    _completion_frame().to_excel(completion, sheet_name="Completion", index=False)

    report = service.process_file(completion)

    assert report["status"] == "preview"
    assert report["eligible"] == 1
    assert report["invalid"] == 0
    assert report["applied_records"] == 0
    assert report["applied_fields"] == 0
    assert report["evidence_records"] == 0
    assert report["completed_records"] == 1
    assert report["rows"][0]["after_completeness_pct"] == 100.0
    assert report["rows"][0]["ready_after"] is True
    assert len(report["rows"][0]["evidence"]) == 4
    assert manager.inspect("LUPIN")["quality"]["completeness_pct"] == 50.0
    assert audit.count("LUPIN") == 0
    assert evidence.count("LUPIN") == 0
    repository.close()
    audit.close()
    evidence.close()


def test_completion_apply_preserves_baseline_and_writes_standardized_evidence(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)
    _seed_half_complete(manager)
    before = repository.by_symbol("LUPIN")
    audit = FundamentalFieldUpdateRepository(db_path=str(db_path))
    evidence = FundamentalFieldEvidenceRepository(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        audit_repository=audit,
        evidence_repository=evidence,
    )

    completion = tmp_path / "completion.xlsx"
    _completion_frame().to_excel(completion, sheet_name="Completion", index=False)
    report = service.process_file(completion, apply=True)

    after = repository.by_symbol("LUPIN")
    result = manager.inspect("LUPIN")

    assert report["status"] == "applied"
    assert report["applied_records"] == 1
    assert report["applied_fields"] == 4
    assert report["evidence_records"] == 4
    assert report["completed_records"] == 1
    assert result["quality"]["completeness_pct"] == 100.0
    assert result["quality"]["ready"] is True

    assert after["roce"] == 30.32
    assert after["sales_growth"] == 18.88
    assert after["profit_growth"] == 141.27
    assert after["debt_to_equity"] == 0.29
    assert after["source"] == before["source"] == "legacy_partial_seed"
    assert after["as_of"] == before["as_of"]
    assert after["imported_at"] == before["imported_at"]

    assert after["roe"] == 18.5
    assert after["eps_growth"] == 22.0
    assert after["promoter_holding"] == 47.2
    assert after["pledged"] == 0.0

    latest = evidence.latest_by_field("LUPIN")
    assert latest["roe"]["period_type"] == "ANNUAL_FY"
    assert latest["roe"]["period_label"] == "FY2026"
    assert latest["eps_growth"]["methodology"] == "3Y_CAGR"
    assert latest["eps_growth"]["period_start"] == "FY2023"
    assert latest["eps_growth"]["period_end"] == "FY2026"
    assert latest["promoter_holding"]["period_type"] == "POINT_IN_TIME"
    assert latest["promoter_holding"]["as_of"] == "2026-06-30"
    assert latest["pledged"]["as_of"] == "2026-06-30"
    assert {item["source"] for item in latest.values()} == {"screener"}

    repository.close()
    audit.close()
    evidence.close()


def test_partial_standardized_completion_can_improve_without_forcing_ready(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=200)
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "partial.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "LUPIN",
                "ROE": 18.5,
                "EPS Growth": 22.0,
                "Completion Source": "annual_report",
                "Completion As Of": "2026-03-31",
                "ROE Period": "FY2026",
                "EPS Growth Status": "VALID",
                "EPS Growth Method": "3Y_CAGR",
                "EPS Start Period": "FY2023",
                "EPS End Period": "FY2026",
            }
        ]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)
    result = manager.inspect("LUPIN")

    assert report["invalid"] == 0
    assert report["applied_fields"] == 2
    assert report["evidence_records"] == 2
    assert report["completed_records"] == 0
    assert result["quality"]["completeness_pct"] == 75.0
    assert result["quality"]["missing"] == ["promoter_holding", "pledged"]


def test_completion_rejects_missing_source_and_period_metadata(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "unstandardized.csv"
    pd.DataFrame([{"Symbol": "LUPIN", "ROE": 18.5}]).to_csv(
        completion,
        index=False,
    )

    report = service.process_file(completion, apply=True)

    assert report["eligible"] == 0
    assert report["invalid"] == 1
    errors = report["invalid_rows"][0]["standardization_errors"]
    assert any("source is required" in item for item in errors)
    assert any("ROE Period" in item for item in errors)
    assert manager.inspect("LUPIN")["quality"]["completeness_pct"] == 50.0


def test_eps_cagr_period_must_span_exactly_three_fiscal_years(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    row = _standardized_completion_row()
    row["EPS Start Period"] = "FY2024"
    completion = tmp_path / "bad_period.csv"
    pd.DataFrame([row]).to_csv(completion, index=False)

    report = service.process_file(completion)

    assert report["eligible"] == 0
    assert report["invalid"] == 1
    assert any(
        "exactly 3 fiscal years" in error
        for error in report["invalid_rows"][0]["standardization_errors"]
    )


def test_negative_base_eps_can_be_recorded_as_nm_without_numeric_value(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=365)
    manager.upsert(
        "GVT&D",
        {
            "roce": 20.0,
            "roe": 57.0,
            "sales_growth": 30.0,
            "profit_growth": 40.0,
            "debt_equity": 0.1,
            "promoter_holding": 51.0,
            "pledged": 0.0,
        },
        source="seed",
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    evidence = FundamentalFieldEvidenceRepository(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        evidence_repository=evidence,
    )

    completion = tmp_path / "nm.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "GVT&D",
                "EPS Growth Status": "N/M",
                "EPS Growth Method": "3Y_CAGR",
                "EPS Start Period": "FY2023",
                "EPS End Period": "FY2026",
                "EPS Growth Reason": "NEGATIVE_BASE",
                "EPS Growth Source": "screener",
                "Completion As Of": "2026-03-31",
            }
        ]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)
    result = manager.inspect("GVT&D")

    assert report["eligible"] == 1
    assert report["applied_records"] == 0
    assert report["applied_fields"] == 0
    assert report["evidence_records"] == 1
    assert report["rows"][0]["non_numeric_fields"] == ["eps_growth"]
    assert result["fundamentals"]["eps_growth"] is None
    assert result["quality"]["ready"] is False
    assert result["quality"]["missing"] == ["eps_growth"]

    latest = evidence.latest_by_field("GVT&D")["eps_growth"]
    assert latest["value"] is None
    assert latest["value_status"] == "N/M"
    assert latest["reason"] == "NEGATIVE_BASE"
    assert latest["methodology"] == "3Y_CAGR"
    evidence.close()


def test_completion_rejects_invalid_numeric_values_after_standardization(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    row = _standardized_completion_row()
    row["Promoter Holding"] = 150.0
    completion = tmp_path / "invalid.csv"
    pd.DataFrame([row]).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)

    assert report["eligible"] == 0
    assert report["invalid"] == 1
    assert report["applied_records"] == 0
    assert manager.inspect("LUPIN")["quality"]["completeness_pct"] == 50.0


def test_completion_unknown_symbol_is_reported_not_created(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "unknown.csv"
    pd.DataFrame([{"Symbol": "UNKNOWN", "ROE": 20.0}]).to_csv(
        completion,
        index=False,
    )

    report = service.process_file(completion, apply=True)

    assert report["unknown_symbols"] == 1
    assert report["applied_records"] == 0
    assert manager.inspect("UNKNOWN") is None


def test_completion_ignores_already_present_values_but_requires_metadata_for_new_field(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "overwrite.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "LUPIN",
                "ROCE": 999.0,
                "ROE": 19.0,
                "Completion Source": "annual_report",
                "Completion As Of": "2026-03-31",
                "ROE Period": "FY2026",
            }
        ]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)
    result = manager.inspect("LUPIN")

    assert report["invalid"] == 0
    assert report["applied_fields"] == 1
    assert result["fundamentals"]["roce"] == 30.32
    assert result["fundamentals"]["roe"] == 19.0
