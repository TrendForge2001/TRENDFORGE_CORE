from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from core.database import database_health, initialize_database
from services.fundamental_bulk_ingestion_service import (
    FundamentalBulkIngestionService,
)
from services.fundamental_completion_service import FundamentalCompletionService
from services.fundamental_coverage_service import FundamentalCoverageService
from services.fundamental_data_manager import FundamentalDataManager


class FakeUniverse:
    def __init__(self, symbols):
        self._members = [
            SimpleNamespace(symbol=symbol, name=symbol)
            for symbol in symbols
        ]

    def ensure_loaded(self, refresh=False):
        del refresh
        return list(self._members)


def _row(symbol: str) -> dict:
    return {
        "Symbol": symbol,
        "ROCE": 30.0,
        "ROE": 20.0,
        "Sales Growth": 25.0,
        "Profit Growth": 25.0,
        "EPS Growth": 25.0,
        "Debt/Equity": 0.2,
        "Promoter Holding": 70.0,
        "Pledged %": 0.0,
        "Completion Source Type": "SCREENER",
        "Completion Source": "screener",
        "Completion Source Ref": f"https://example.test/{symbol}",
        "Completion As Of": "2026-09-30",
        "ROE Period": "FY2026",
        "EPS Growth Status": "VALID",
        "EPS Growth Method": "3Y_CAGR",
        "EPS Start Period": "FY2023",
        "EPS End Period": "FY2026",
        "Promoter Holding As Of": "2026-09-30",
        "Pledged As Of": "2026-09-30",
    }


def _service(tmp_path, symbols):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(
        db_path=str(db_path),
        max_age_days=365,
    )
    universe = FakeUniverse(symbols)
    completion = FundamentalCompletionService(
        manager=manager,
        universe=universe,
    )
    coverage = FundamentalCoverageService(
        manager=manager,
        universe=universe,
    )
    return (
        FundamentalBulkIngestionService(
            completion=completion,
            coverage=coverage,
        ),
        manager,
    )


def test_database_includes_fundamental_bulk_runs_table(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    health = database_health(str(db_path))

    assert health["status"] == "ready"
    assert "fundamental_bulk_runs" not in health.get(
        "missing_tables",
        [],
    )


def test_bulk_requires_clean_preview_then_applies_and_resumes(tmp_path):
    symbols = [f"SYM{i:03d}" for i in range(30)]
    service, manager = _service(tmp_path, symbols)
    path = tmp_path / "bulk.csv"
    pd.DataFrame([_row(symbol) for symbol in symbols]).to_csv(
        path,
        index=False,
    )

    preview = service.process_file(
        path,
        run_id="bulk-1",
        stage_size=25,
        apply=False,
        source_file_name="bulk.csv",
    )

    assert preview["version"] == "R69.5"
    assert preview["status"] == "preview_ready"
    assert preview["stage"]["range"] == {
        "start": 0,
        "end": 25,
        "row_count": 25,
        "stage_size": 25,
    }
    assert preview["stage"]["gate"]["pass"] is True
    assert preview["next_offset"] == 0
    assert manager.repository.count() == 0

    applied = service.process_file(
        path,
        run_id="bulk-1",
        stage_size=25,
        apply=True,
        source_file_name="bulk.csv",
    )

    assert applied["status"] == "stage_applied"
    assert applied["run"]["next_offset"] == 25
    assert applied["remaining_rows"] == 5
    assert applied["stage"]["coverage_delta"][
        "database_records"
    ] == 25
    assert applied["stage"]["coverage_delta"][
        "scanner_ready_records"
    ] == 25
    assert manager.repository.count() == 25

    second_preview = service.process_file(
        path,
        run_id="bulk-1",
        stage_size=50,
        apply=False,
        source_file_name="bulk.csv",
    )
    assert second_preview["stage"]["range"]["start"] == 25
    assert second_preview["stage"]["range"]["end"] == 30

    completed = service.process_file(
        path,
        run_id="bulk-1",
        stage_size=50,
        apply=True,
        source_file_name="bulk.csv",
    )

    assert completed["status"] == "completed"
    assert completed["run"]["next_offset"] == 30
    assert completed["run"]["aggregate"]["processed_rows"] == 30
    assert completed["run"]["aggregate"]["stages_applied"] == 2
    assert completed["run"]["coverage_after"][
        "scanner_ready_records"
    ] == 30
    assert manager.repository.count() == 30


def test_apply_without_prior_preview_is_fail_closed(tmp_path):
    symbols = ["AAA"]
    service, manager = _service(tmp_path, symbols)
    path = tmp_path / "bulk.csv"
    pd.DataFrame([_row("AAA")]).to_csv(path, index=False)

    result = service.process_file(
        path,
        run_id="bulk-preview-required",
        stage_size=25,
        apply=True,
    )

    assert result["status"] == "preview_required"
    assert manager.repository.count() == 0
    assert service.get("bulk-preview-required")[
        "last_preview_gate_pass"
    ] is True


def test_duplicate_symbol_blocks_stage(tmp_path):
    service, manager = _service(tmp_path, ["AAA", "BBB"])
    path = tmp_path / "dup.csv"
    pd.DataFrame([_row("AAA"), _row("AAA")]).to_csv(
        path,
        index=False,
    )

    preview = service.process_file(
        path,
        run_id="bulk-duplicate",
        stage_size=25,
    )

    assert preview["status"] == "preview_blocked"
    gate = preview["stage"]["gate"]
    assert gate["duplicate_symbols"] == 1
    assert gate["duplicate_symbol_list"] == ["AAA"]
    assert "duplicate_symbols" in gate["reasons"]

    blocked = service.process_file(
        path,
        run_id="bulk-duplicate",
        stage_size=25,
        apply=True,
    )
    assert blocked["status"] == "apply_blocked"
    assert manager.repository.count() == 0


def test_existing_present_field_is_reported_as_overwrite_attempt(tmp_path):
    service, manager = _service(tmp_path, ["AAA"])
    manager.upsert(
        "AAA",
        {"roce": 22.0},
        source="verified_seed",
        as_of=datetime.now(timezone.utc).isoformat(),
    )
    path = tmp_path / "overwrite.csv"
    pd.DataFrame([_row("AAA")]).to_csv(path, index=False)

    result = service.process_file(
        path,
        run_id="bulk-overwrite",
        stage_size=25,
    )

    assert result["status"] == "preview_blocked"
    gate = result["stage"]["gate"]
    assert gate["overwrite_attempts"] == 1
    assert "overwrite_attempts" in gate["reasons"]
    assert manager.inspect("AAA")["fundamentals"]["roce"] == 22.0


def test_unknown_symbol_and_invalid_evidence_block_apply(tmp_path):
    service, manager = _service(tmp_path, ["AAA"])
    bad = _row("OUTSIDE")
    bad["Completion Source Ref"] = ""
    path = tmp_path / "bad.csv"
    pd.DataFrame([bad]).to_csv(path, index=False)

    result = service.process_file(
        path,
        run_id="bulk-bad",
        stage_size=25,
    )

    assert result["status"] == "preview_blocked"
    assert result["stage"]["gate"]["unknown_symbols"] == 1
    assert manager.repository.count() == 0


def test_same_run_id_rejects_different_file_hash(tmp_path):
    service, _ = _service(tmp_path, ["AAA", "BBB"])
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    pd.DataFrame([_row("AAA")]).to_csv(first, index=False)
    pd.DataFrame([_row("BBB")]).to_csv(second, index=False)

    service.process_file(
        first,
        run_id="bulk-hash",
        stage_size=25,
    )

    with pytest.raises(ValueError, match="different bulk file SHA256"):
        service.process_file(
            second,
            run_id="bulk-hash",
            stage_size=25,
        )


def test_invalid_stage_size_is_rejected(tmp_path):
    service, _ = _service(tmp_path, ["AAA"])
    path = tmp_path / "bulk.csv"
    pd.DataFrame([_row("AAA")]).to_csv(path, index=False)

    with pytest.raises(ValueError, match="stage_size must be one of"):
        service.process_file(
            path,
            run_id="bulk-stage",
            stage_size=10,
        )
