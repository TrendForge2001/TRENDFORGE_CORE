from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from core.database import initialize_database
from database.repositories.fundamentals_repository import FundamentalsRepository
from services.fundamental_data_manager import FundamentalDataManager


def complete_values():
    return {
        "roce": 16.0,
        "roe": 18.0,
        "sales_growth": 12.0,
        "profit_growth": 15.0,
        "eps_growth": 11.0,
        "debt_equity": 0.45,
        "promoter_holding": 50.3,
        "pledged": 0.0,
    }


def test_repository_partial_update_preserves_existing_non_null_fields(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))

    repository.save(
        {
            "symbol": "RELIANCE",
            "roce": 16.0,
            "roe": 18.0,
            "sales_growth": 12.0,
            "source": "seed",
        }
    )
    repository.save(
        {
            "symbol": "NSE:RELIANCE",
            "roe": 19.0,
            "roce": None,
            "sales_growth": None,
            "source": "manual",
        }
    )

    row = repository.by_symbol("RELIANCE")
    assert row["roce"] == 16.0
    assert row["sales_growth"] == 12.0
    assert row["roe"] == 19.0
    assert row["source"] == "manual"
    repository.close()


def test_partial_file_import_merges_without_erasing_verified_fields(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=365)

    manager.upsert(
        "RELIANCE",
        complete_values(),
        source="verified",
        as_of=datetime.now(timezone.utc).isoformat(),
    )

    partial = tmp_path / "partial.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "RELIANCE",
                "ROE": 20.0,
                "Source": "manual_patch",
            }
        ]
    ).to_csv(partial, index=False)

    report = manager.import_file(partial, source="fallback")
    result = manager.inspect("RELIANCE")

    assert report["imported"] == 1
    assert result is not None
    assert result["fundamentals"]["roe"] == 20.0
    assert result["fundamentals"]["roce"] == 16.0
    assert result["fundamentals"]["eps_growth"] == 11.0
    assert result["metadata"]["source"] == "manual_patch"
    repository.close()


def test_manual_partial_update_reports_completeness_and_missing_fields(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=365)

    result = manager.upsert(
        "nse:abc",
        {"roce": 20.0, "roe": 18.0},
        source="manual",
    )

    assert result["symbol"] == "ABC"
    assert result["quality"]["ready"] is False
    assert result["quality"]["completeness_pct"] == 25.0
    assert "sales_growth" in result["quality"]["missing"]
    assert "pledged" in result["quality"]["missing"]
    repository.close()


def test_manual_update_rejects_invalid_contract_values(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository)

    with pytest.raises(ValueError, match="promoter_holding"):
        manager.upsert(
            "ABC",
            {"promoter_holding": 125.0},
            source="manual",
        )

    assert repository.by_symbol("ABC") is None
    repository.close()


def test_complete_record_is_ready_when_fresh(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=365)

    result = manager.upsert(
        "RELIANCE",
        complete_values(),
        source="manual",
        as_of=datetime.now(timezone.utc).isoformat(),
    )

    assert result["quality"]["contract_ready"] is True
    assert result["quality"]["ready"] is True
    assert result["quality"]["completeness_pct"] == 100.0
    assert result["quality"]["missing"] == []
    repository.close()


def test_complete_but_old_record_is_stale_and_not_ready(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)
    old = datetime.now(timezone.utc) - timedelta(days=300)

    result = manager.upsert(
        "OLD",
        complete_values(),
        source="manual",
        as_of=old.isoformat(),
    )

    assert result["quality"]["contract_ready"] is True
    assert result["quality"]["stale"] is True
    assert result["quality"]["ready"] is False
    assert "Fundamental snapshot is stale or undated" in result["quality"]["warnings"]
    repository.close()


def test_manager_report_summarizes_ready_incomplete_and_stale(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=200)

    manager.upsert(
        "READY",
        complete_values(),
        source="manual",
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    manager.upsert("PARTIAL", {"roce": 10.0}, source="manual")
    manager.upsert(
        "STALE",
        complete_values(),
        source="manual",
        as_of=(datetime.now(timezone.utc) - timedelta(days=300)).isoformat(),
    )

    report = manager.report()

    assert report["total_records"] == 3
    assert report["ready_records"] == 1
    assert report["incomplete_records"] == 2
    assert report["stale_records"] == 1
    assert report["returned"] == 3
    repository.close()


def test_template_csv_and_xlsx_are_blank_with_canonical_headers():
    manager = FundamentalDataManager.__new__(FundamentalDataManager)

    csv_bytes = manager.template_csv()
    csv_text = csv_bytes.decode("utf-8-sig")
    assert csv_text.splitlines()[0].startswith("Symbol,ROCE,ROE")
    assert len(csv_text.splitlines()) == 1

    xlsx_bytes = manager.template_xlsx()
    assert len(xlsx_bytes) > 100
    frame = pd.read_excel(__import__("io").BytesIO(xlsx_bytes))
    assert list(frame.columns) == list(FundamentalDataManager.TEMPLATE_COLUMNS)
    assert frame.empty


def test_upload_provenance_uses_original_filename(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=365)

    temp_file = tmp_path / "server-temp.xlsx"
    pd.DataFrame(
        [
            {
                "Symbol": "INFY",
                "ROCE": 25.0,
                "ROE": 28.0,
                "Sales Growth": 10.0,
                "Profit Growth": 12.0,
                "EPS Growth": 12.0,
                "Debt/Equity": 0.1,
                "Promoter Holding": 14.6,
                "Pledged %": 0.0,
            }
        ]
    ).to_excel(temp_file, index=False)

    manager.import_file(
        temp_file,
        source="upload",
        source_file_name="My Fundamentals.xlsx",
    )
    result = manager.inspect("INFY")

    assert result is not None
    assert result["metadata"]["source_file"] == "My Fundamentals.xlsx"
    repository.close()
