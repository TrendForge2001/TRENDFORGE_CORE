from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from core.database import initialize_database
from database.database import Database
from database.migrations import scan_run_audit
from database.repositories.scan_run_audit_repository import (
    DuplicateScanRunIdError,
    ScanRunAuditRepository,
)
from providers.routed_market_data_provider import RoutedMarketDataProvider


def _frame():
    return pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
            "Volume": [1000],
        }
    )


def test_scan_run_audit_repository_round_trip(tmp_path: Path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repo = ScanRunAuditRepository(db_path=str(db_path))

    saved = repo.save(
        {
            "run_id": "run-123",
            "scan_type": "nifty500",
            "started_at": "2026-10-13T04:00:00+00:00",
            "finished_at": "2026-10-13T04:05:00+00:00",
            "duration_sec": 300.0,
            "requested_symbols": 500,
            "completed_symbols": 500,
            "error_symbols": 0,
            "missing_symbols": 0,
            "enrichment_failures": 0,
            "execution_errors": 0,
            "full_universe": True,
            "source_security_count": 501,
            "tradable_security_count": 500,
            "provider_counts": {"KiteProvider": 499, "YahooFinanceProvider": 1},
            "fallback_count": 1,
            "nse_resolution_count": 0,
            "error_details": {},
            "metadata": {"period": "6mo"},
        }
    )

    assert saved["run_id"] == "run-123"
    assert saved["full_universe"] is True
    assert saved["provider_counts"]["KiteProvider"] == 499
    assert saved["fallback_count"] == 1

    latest = repo.latest(5)
    assert len(latest) == 1
    assert latest[0]["metadata"]["period"] == "6mo"


def test_router_observability_counts_primary_fallback_and_nse_resolution():
    class Kite:
        pass

    class Yahoo:
        pass

    router = RoutedMarketDataProvider([Kite(), Yahoo()])
    router.last_provider = {
        "AAA": "Kite",
        "BBB": "Yahoo",
        "CCC": "Kite[NSE:NEWCCC]",
    }
    router.last_errors = {
        "AAA": [],
        "BBB": ["Kite: missing"],
        "CCC": ["Kite: missing"],
    }

    snapshot = router.observability_snapshot(["AAA", "BBB", "CCC"])

    assert snapshot["provider_counts"] == {
        "Kite": 1,
        "Yahoo": 1,
        "Kite[NSE:NEWCCC]": 1,
    }
    assert snapshot["fallback_count"] == 1
    assert snapshot["nse_resolution_count"] == 1


def test_router_begin_observation_clears_previous_run_state():
    router = RoutedMarketDataProvider([object()])
    router.last_provider = {"AAA": "Old"}
    router.last_errors = {"AAA": ["old error"]}

    router.begin_observation()

    assert router.last_provider == {}
    assert router.last_errors == {}


def test_scan_run_audit_health_tolerates_uninitialized_schema(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    repo = ScanRunAuditRepository(db_path=str(db_path))

    health = repo.health()

    assert health["status"] == "not_initialized"
    assert health["reason"] == "schema_not_initialized"
    assert health["records"] == 0


def test_scan_run_audit_is_immutable_by_run_id(tmp_path: Path):
    db_path = tmp_path / "immutable.db"
    initialize_database(str(db_path))
    repo = ScanRunAuditRepository(db_path=str(db_path))

    first = repo.save(
        {
            "run_id": "same-run",
            "scan_type": "nifty500",
            "outcome": "completed",
            "http_status": 200,
            "started_at": "2026-10-13T10:00:00+00:00",
            "finished_at": "2026-10-13T10:01:00+00:00",
            "duration_sec": 60.0,
            "requested_symbols": 25,
            "completed_symbols": 25,
            "error_symbols": 0,
            "missing_symbols": 0,
            "enrichment_failures": 0,
            "execution_errors": 0,
            "full_universe": False,
            "provider_counts": {"KiteProvider": 25},
            "fallback_count": 0,
            "nse_resolution_count": 0,
            "error_details": {},
            "metadata": {"period": "6mo"},
        }
    )

    with pytest.raises(
        DuplicateScanRunIdError,
        match="already exists",
    ):
        repo.save(
            {
                "run_id": "same-run",
                "scan_type": "nifty500",
                "outcome": "failed",
                "http_status": 503,
                "started_at": "2026-10-13T11:00:00+00:00",
                "finished_at": "2026-10-13T11:00:01+00:00",
                "duration_sec": 1.0,
                "requested_symbols": 25,
                "completed_symbols": 0,
                "error_symbols": 0,
                "missing_symbols": 0,
                "enrichment_failures": 0,
                "execution_errors": 0,
                "full_universe": False,
                "provider_counts": {},
                "fallback_count": 0,
                "nse_resolution_count": 0,
                "error_details": {"fatal": "must not overwrite"},
                "metadata": {},
            }
        )

    preserved = repo.by_run_id("same-run")
    assert preserved["id"] == first["id"]
    assert preserved["outcome"] == "completed"
    assert preserved["completed_symbols"] == 25
    assert preserved["provider_counts"] == {"KiteProvider": 25}


def test_scan_run_audit_migration_preserves_legacy_rows(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    db = Database(str(db_path))
    try:
        db.execute(
            """
            CREATE TABLE scan_run_audit(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL UNIQUE,
                scan_type TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                requested_symbols INTEGER NOT NULL,
                completed_symbols INTEGER NOT NULL,
                error_symbols INTEGER NOT NULL,
                missing_symbols INTEGER NOT NULL,
                enrichment_failures INTEGER NOT NULL,
                execution_errors INTEGER NOT NULL,
                full_universe INTEGER NOT NULL DEFAULT 0,
                source_security_count INTEGER,
                tradable_security_count INTEGER,
                provider_counts_json TEXT NOT NULL,
                fallback_count INTEGER NOT NULL DEFAULT 0,
                nse_resolution_count INTEGER NOT NULL DEFAULT 0,
                error_details_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        db.execute(
            """
            INSERT INTO scan_run_audit(
                run_id, scan_type, started_at, finished_at,
                duration_sec, requested_symbols, completed_symbols,
                error_symbols, missing_symbols, enrichment_failures,
                execution_errors, full_universe, source_security_count,
                tradable_security_count, provider_counts_json,
                fallback_count, nse_resolution_count,
                error_details_json, metadata_json, created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                "legacy-run",
                "nifty500",
                "2026-10-13T10:00:00+00:00",
                "2026-10-13T10:01:00+00:00",
                60.0,
                25,
                25,
                0,
                0,
                0,
                0,
                0,
                501,
                500,
                '{"KiteProvider": 25}',
                0,
                0,
                '{}',
                '{"period": "6mo"}',
                "2026-10-13T10:01:00+00:00",
            ),
        )

        scan_run_audit.migrate(db)

        row = db.fetchone(
            """
            SELECT run_id, outcome, http_status,
                   failure_stage, failure_message
            FROM scan_run_audit
            WHERE run_id=?
            """,
            ("legacy-run",),
        )
    finally:
        db.close()

    assert row["run_id"] == "legacy-run"
    assert row["outcome"] == "completed"
    assert row["http_status"] == 200
    assert row["failure_stage"] is None
    assert row["failure_message"] is None
