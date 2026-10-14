from __future__ import annotations

from pathlib import Path

import pytest

from core.database import initialize_database
from database.database import Database
from database.repositories.scan_continuation_repository import (
    ContinuationUnavailableError,
    DuplicateContinuationError,
    ScanContinuationRepository,
)


def _repo(tmp_path: Path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    db = Database(str(db_path))
    return db, ScanContinuationRepository(db)


def test_continuation_lifecycle_is_one_time_and_persists_symbols(tmp_path: Path):
    db, repo = _repo(tmp_path)
    try:
        created = repo.create(
            token="token-a",
            parent_run_id="parent-run",
            lineage_root_run_id="parent-run",
            generation=1,
            symbols=["AAA", "bbb", "AAA"],
            request={"period": "6mo", "interval": "1d"},
        )

        assert created["status"] == "pending"
        assert created["symbols"] == ["AAA", "BBB"]
        assert created["generation"] == 1

        claimed = repo.claim("token-a", "child-run")
        assert claimed["status"] == "active"
        assert claimed["child_run_id"] == "child-run"

        with pytest.raises(ContinuationUnavailableError):
            repo.claim("token-a", "other-child")

        consumed = repo.consume("token-a", "child-run")
        assert consumed["status"] == "consumed"
        assert consumed["child_run_id"] == "child-run"

        with pytest.raises(ContinuationUnavailableError):
            repo.claim("token-a", "replay-run")
    finally:
        db.close()


def test_continuation_can_be_restored_after_child_commit_failure(tmp_path: Path):
    db, repo = _repo(tmp_path)
    try:
        repo.create(
            token="token-b",
            parent_run_id="parent-run",
            lineage_root_run_id="root-run",
            generation=2,
            symbols=["AAA"],
            request={"period": "6mo"},
        )
        repo.claim("token-b", "child-run")
        repo.consume("token-b", "child-run")

        restored = repo.restore_pending("token-b", "child-run")

        assert restored["status"] == "pending"
        assert restored["child_run_id"] is None
        assert restored["claimed_at"] is None
        assert restored["consumed_at"] is None

        reclaimed = repo.claim("token-b", "retry-run")
        assert reclaimed["status"] == "active"
        assert reclaimed["child_run_id"] == "retry-run"
    finally:
        db.close()


def test_only_one_continuation_exists_per_parent_run(tmp_path: Path):
    db, repo = _repo(tmp_path)
    try:
        repo.create(
            token="token-c1",
            parent_run_id="parent-run",
            lineage_root_run_id="parent-run",
            generation=1,
            symbols=["AAA"],
            request={},
        )

        with pytest.raises(DuplicateContinuationError):
            repo.create(
                token="token-c2",
                parent_run_id="parent-run",
                lineage_root_run_id="parent-run",
                generation=1,
                symbols=["BBB"],
                request={},
            )
    finally:
        db.close()


def test_continuation_health_counts_states(tmp_path: Path):
    db, repo = _repo(tmp_path)
    try:
        repo.create(
            token="pending-token",
            parent_run_id="pending-parent",
            lineage_root_run_id="pending-parent",
            generation=1,
            symbols=["AAA"],
            request={},
        )
        repo.create(
            token="consumed-token",
            parent_run_id="consumed-parent",
            lineage_root_run_id="consumed-parent",
            generation=1,
            symbols=["BBB"],
            request={},
        )
        repo.claim("consumed-token", "child")
        repo.consume("consumed-token", "child")

        health = repo.health()

        assert health["status"] == "ready"
        assert health["records"] == 2
        assert health["pending"] == 1
        assert health["active"] == 0
        assert health["consumed"] == 1
    finally:
        db.close()
