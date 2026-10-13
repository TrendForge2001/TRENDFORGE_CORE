from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.database import initialize_database
from database.repositories.scan_run_audit_repository import (
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
