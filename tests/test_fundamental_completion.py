from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO

import pandas as pd

from core.database import database_health, initialize_database
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


def _completion_frame(symbol: str = "LUPIN") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Symbol": symbol,
                "ROCE": 999.0,
                "ROE": 18.5,
                "EPS Growth": 22.0,
                "Promoter Holding": 47.2,
                "Pledged %": 0.0,
                "Completion Source": "manual_research",
                "Completion As Of": "2026-10-06",
            }
        ]
    )


def test_database_initialization_includes_completion_audit_table(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    health = database_health(str(db_path))

    assert health["status"] == "ready"
    assert health["tables"] >= 14


def test_completion_export_contains_only_union_of_missing_fields(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=200)
    _seed_half_complete(manager, "LUPIN")
    _seed_half_complete(manager, "BSE")

    service = FundamentalCompletionService(manager=manager)
    frame = service.completion_frame()

    assert list(frame["Symbol"]) == ["BSE", "LUPIN"]
    assert list(frame.columns) == [
        "Symbol",
        "ROE",
        "EPS Growth",
        "Promoter Holding",
        "Pledged %",
        "Completion Source",
        "Completion As Of",
        "Current Completeness %",
        "Missing Fields",
        "Snapshot As Of",
        "Baseline Source",
    ]
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


def test_completion_preview_never_writes_and_reports_ready_after(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)
    _seed_half_complete(manager)
    audit = FundamentalFieldUpdateRepository(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        audit_repository=audit,
    )

    completion = tmp_path / "completion.xlsx"
    _completion_frame().to_excel(
        completion,
        sheet_name="Completion",
        index=False,
    )

    report = service.process_file(completion)

    assert report["status"] == "preview"
    assert report["eligible"] == 1
    assert report["applied_records"] == 0
    assert report["applied_fields"] == 0
    assert report["completed_records"] == 1
    assert report["rows"][0]["after_completeness_pct"] == 100.0
    assert report["rows"][0]["ready_after"] is True
    assert manager.inspect("LUPIN")["quality"]["completeness_pct"] == 50.0
    assert audit.count("LUPIN") == 0
    repository.close()
    audit.close()


def test_completion_apply_only_fills_missing_and_preserves_baseline_metadata(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)
    _seed_half_complete(manager)
    before = repository.by_symbol("LUPIN")
    audit = FundamentalFieldUpdateRepository(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        audit_repository=audit,
    )

    completion = tmp_path / "completion.xlsx"
    _completion_frame().to_excel(
        completion,
        sheet_name="Completion",
        index=False,
    )
    report = service.process_file(completion, apply=True)

    after = repository.by_symbol("LUPIN")
    result = manager.inspect("LUPIN")

    assert report["status"] == "applied"
    assert report["applied_records"] == 1
    assert report["applied_fields"] == 4
    assert report["completed_records"] == 1
    assert result["quality"]["completeness_pct"] == 100.0
    assert result["quality"]["ready"] is True

    # Existing baseline values cannot be overwritten by completion workbook.
    assert after["roce"] == 30.32
    assert after["sales_growth"] == 18.88
    assert after["profit_growth"] == 141.27
    assert after["debt_to_equity"] == 0.29

    # Baseline provenance/freshness remains conservative.
    assert after["source"] == before["source"] == "legacy_partial_seed"
    assert after["as_of"] == before["as_of"]
    assert after["imported_at"] == before["imported_at"]

    assert after["roe"] == 18.5
    assert after["eps_growth"] == 22.0
    assert after["promoter_holding"] == 47.2
    assert after["pledged"] == 0.0

    history = audit.by_symbol("LUPIN")
    assert len(history) == 4
    assert {item["field"] for item in history} == {
        "roe",
        "eps_growth",
        "promoter_holding",
        "pledged",
    }
    assert {item["source"] for item in history} == {"manual_research"}
    assert {item["as_of"] for item in history} == {"2026-10-06"}

    repository.close()
    audit.close()


def test_partial_completion_can_improve_without_forcing_ready(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=200)
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "partial.csv"
    pd.DataFrame(
        [{"Symbol": "LUPIN", "ROE": 18.5, "EPS Growth": 22.0}]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)
    result = manager.inspect("LUPIN")

    assert report["applied_fields"] == 2
    assert report["completed_records"] == 0
    assert result["quality"]["completeness_pct"] == 75.0
    assert result["quality"]["missing"] == ["promoter_holding", "pledged"]


def test_completion_rejects_invalid_missing_values(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "invalid.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "LUPIN",
                "ROE": 18.5,
                "EPS Growth": 22.0,
                "Promoter Holding": 150.0,
                "Pledged %": 0.0,
            }
        ]
    ).to_csv(completion, index=False)

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
    pd.DataFrame(
        [{"Symbol": "UNKNOWN", "ROE": 20.0}]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)

    assert report["unknown_symbols"] == 1
    assert report["applied_records"] == 0
    assert manager.inspect("UNKNOWN") is None


def test_completion_ignores_values_for_fields_already_present(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    _seed_half_complete(manager)
    service = FundamentalCompletionService(manager=manager)

    completion = tmp_path / "overwrite.csv"
    pd.DataFrame(
        [{"Symbol": "LUPIN", "ROCE": 999.0, "ROE": 19.0}]
    ).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)
    result = manager.inspect("LUPIN")

    assert report["applied_fields"] == 1
    assert result["fundamentals"]["roce"] == 30.32
    assert result["fundamentals"]["roe"] == 19.0
