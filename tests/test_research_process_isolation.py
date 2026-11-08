"""Real child execution, crash containment and uploaded scan recovery."""

import base64
import gzip
import json
from copy import deepcopy

import pytest

from core.database import initialize_database
from database.database import Database
from database.repositories.research_batches import ResearchBatchRepository
from services.research_batches import ResearchBatchManager
from services.research_recovery import (
    SEED_ENV,
    recover_seed,
    restore_configured_snapshot,
    scan_workbook_batch,
)
from services.research_report import build_report
from tests.support.research_candles import technical_service


@pytest.mark.parametrize("kind", ["scan", "backtest"])
def test_real_isolated_job_commits_report_without_using_parent_market(tmp_path, kind):
    path = str(tmp_path / "test.db")
    initialize_database(path)
    technical = technical_service(path)
    technical.market_data = None  # Any parent-side history request would fail.
    manager = ResearchBatchManager(
        technical, isolated=True, worker_module="tests.support.research_worker"
    )
    try:
        batch = manager.submit(
            kind,
            {
                "horizon": "intraday",
                "stock_list": "NIFTY 100",
                "strategy_id": "tf_ema20_50_bearish_pivot",
                "symbols": ["TCS", "SBIN"],
                "short_borrow_available": True,
            },
        )
        manager.futures[batch["batch_id"]].result(timeout=30)
        saved = manager.repository.get(batch["batch_id"])
        assert saved["status"] == "completed", saved["error_code"]
        assert saved["report"]["run_id"] == batch["batch_id"]
        assert saved["report"]["xlsx_sha256"]
        assert saved["phase_total"] == 2
    finally:
        manager.close(wait=True)
        technical.repository.close()


def test_child_crash_is_failed_and_next_job_still_completes(tmp_path):
    path = str(tmp_path / "test.db")
    initialize_database(path)
    technical = technical_service(path)
    manager = ResearchBatchManager(
        technical, isolated=True, worker_module="tests.support.no_such_worker"
    )
    request = {
        "horizon": "short_swing",
        "stock_list": "NIFTY 50",
        "strategy_id": "tf_ema9_26_bullish_pivot",
        "symbols": ["TCS"],
    }
    try:
        batch = manager.submit("backtest", request)
        manager.futures[batch["batch_id"]].result(timeout=10)
        assert (
            manager.repository.get(batch["batch_id"])["error_code"]
            == "research_worker_exited"
        )
        manager.worker_module = "tests.support.research_worker"
        batch = manager.submit("backtest", request)
        manager.futures[batch["batch_id"]].result(timeout=30)
        assert manager.repository.get(batch["batch_id"])["status"] == "completed"
    finally:
        manager.close(wait=True)
        technical.repository.close()


def scan_snapshot():
    report = build_report(
        {
            "run_id": "batch-upload",
            "strategy_id": "tf_intraday_vwma9_26_short",
            "mode": "intraday",
            "period": "60d",
            "requested_symbols": 1,
            "completed_symbols": 1,
            "error_symbols": 0,
            "results": [{"symbol": "TCS", "signal": "WAIT", "score": 0}],
        },
        kind="scan",
        horizon="intraday",
        stock_list="NIFTY 100",
    )
    return base64.b64decode(report["xlsx_base64"])


def test_uploaded_workbook_recovery_is_atomic_idempotent_and_preserves_original(
    tmp_path, monkeypatch
):
    content = scan_snapshot()
    batch = scan_workbook_batch(content)
    assert base64.b64decode(batch["report"]["xlsx_base64"]) == content
    assert batch["kind"] == "scan" and batch["report"]["rows"][0]["signal"] == "WAIT"
    path = str(tmp_path / "test.db")
    initialize_database(path)
    db = Database(path)
    repository = ResearchBatchRepository(db)
    seed = {
        "format": "scanner_workbook_v1",
        "xlsx_base64": base64.b64encode(content).decode(),
    }
    monkeypatch.setenv(
        SEED_ENV, base64.b64encode(gzip.compress(json.dumps(seed).encode())).decode()
    )
    monkeypatch.setenv("DATABASE_PATH", path)
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    try:
        assert restore_configured_snapshot() == "restored"
        assert recover_seed(repository) == "already_present"
        assert (
            repository.latest("scan", completed_only=True)[0]["batch_id"]
            == "batch-upload"
        )
        conflict = deepcopy(batch)
        conflict["report"]["generated_at"] = "different provenance"
        assert not repository.restore_completed(conflict)
        assert repository.get("batch-upload")["report"] == batch["report"]
        repository.create("newer-failed", "backtest", batch["request"])
        repository.fail("newer-failed", "research_worker_exited")
        assert repository.latest()[0]["batch_id"] == "newer-failed"
        assert (
            repository.latest("scan", 1, completed_only=True)[0]["batch_id"]
            == "batch-upload"
        )
    finally:
        db.close()


@pytest.mark.parametrize("seed", ["bad base64!", "eA=="])
def test_invalid_seed_cannot_hide_existing_batches(tmp_path, monkeypatch, seed):
    path = str(tmp_path / "test.db")
    initialize_database(path)
    db = Database(path)
    monkeypatch.setenv(SEED_ENV, seed)
    try:
        assert recover_seed(ResearchBatchRepository(db)) == "invalid"
        assert not ResearchBatchRepository(db).latest()
    finally:
        db.close()
