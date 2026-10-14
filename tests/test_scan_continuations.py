from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.database import initialize_database
from database.database import Database
from database.repositories.scan_continuation_repository import (
    ContinuationAttemptLimitError,
    ContinuationExpiredError,
    ContinuationUnavailableError,
    DuplicateContinuationError,
    ScanContinuationRepository,
)
from services.scan_continuation_service import (
    ContinuationDepthExceededError,
    ScanContinuationService,
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



class FakeClock:
    def __init__(self, start: datetime):
        self.current = start

    def now(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def _guarded_repo(tmp_path: Path, clock: FakeClock):
    db_path = tmp_path / "guarded.db"
    initialize_database(str(db_path))
    db = Database(str(db_path))
    return db, ScanContinuationRepository(
        db,
        now_provider=clock.now,
    )


def test_continuation_expires_after_ttl(tmp_path: Path):
    clock = FakeClock(
        datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    )
    db, repo = _guarded_repo(tmp_path, clock)
    try:
        created = repo.create(
            token="ttl-token",
            parent_run_id="ttl-parent",
            lineage_root_run_id="ttl-parent",
            generation=1,
            symbols=["AAA"],
            request={},
            ttl_seconds=60,
            max_claim_attempts=3,
        )
        assert created["expires_at"] == (
            clock.current + timedelta(seconds=60)
        ).isoformat()

        clock.advance(seconds=61)

        with pytest.raises(
            ContinuationExpiredError,
            match="expired",
        ):
            repo.inspect_available("ttl-token")

        with pytest.raises(
            ContinuationExpiredError,
            match="expired",
        ):
            repo.claim("ttl-token", "ttl-child")
    finally:
        db.close()


def test_continuation_claim_attempt_budget_is_not_reset_by_release(tmp_path: Path):
    clock = FakeClock(
        datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    )
    db, repo = _guarded_repo(tmp_path, clock)
    try:
        repo.create(
            token="attempt-token",
            parent_run_id="attempt-parent",
            lineage_root_run_id="attempt-parent",
            generation=1,
            symbols=["AAA"],
            request={},
            ttl_seconds=3600,
            max_claim_attempts=2,
        )

        first = repo.claim("attempt-token", "child-1")
        assert first["claim_attempts"] == 1
        repo.release("attempt-token", "child-1")

        second = repo.claim("attempt-token", "child-2")
        assert second["claim_attempts"] == 2
        repo.release("attempt-token", "child-2")

        with pytest.raises(
            ContinuationAttemptLimitError,
            match="claim limit exhausted",
        ):
            repo.claim("attempt-token", "child-3")

        record = repo.by_token("attempt-token")
        assert record["status"] == "pending"
        assert record["claim_attempts"] == 2
        assert record["max_claim_attempts"] == 2
    finally:
        db.close()


def test_stale_active_continuation_is_recovered_without_resetting_attempts(tmp_path: Path):
    clock = FakeClock(
        datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    )
    db, repo = _guarded_repo(tmp_path, clock)
    try:
        repo.create(
            token="stale-token",
            parent_run_id="stale-parent",
            lineage_root_run_id="stale-parent",
            generation=1,
            symbols=["AAA"],
            request={},
            ttl_seconds=3600,
            max_claim_attempts=3,
        )
        repo.claim("stale-token", "stale-child")

        clock.advance(seconds=1201)
        recovered = repo.recover_stale_active(
            stale_after_seconds=1200
        )

        assert recovered == 1
        record = repo.by_token("stale-token")
        assert record["status"] == "pending"
        assert record["child_run_id"] is None
        assert record["claimed_at"] is None
        assert record["claim_attempts"] == 1
        assert record["recovery_count"] == 1
        assert record["last_recovered_at"] is not None
    finally:
        db.close()


def test_cleanup_removes_expired_pending_and_consumed_records(tmp_path: Path):
    clock = FakeClock(
        datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    )
    db, repo = _guarded_repo(tmp_path, clock)
    try:
        repo.create(
            token="pending-expired",
            parent_run_id="pending-parent",
            lineage_root_run_id="pending-parent",
            generation=1,
            symbols=["AAA"],
            request={},
            ttl_seconds=60,
            max_claim_attempts=3,
        )
        repo.create(
            token="consumed-expired",
            parent_run_id="consumed-parent",
            lineage_root_run_id="consumed-parent",
            generation=1,
            symbols=["BBB"],
            request={},
            ttl_seconds=60,
            max_claim_attempts=3,
        )
        repo.claim("consumed-expired", "child")
        repo.consume("consumed-expired", "child")

        clock.advance(seconds=61)
        deleted = repo.cleanup_expired(
            retention_seconds=0,
            stale_active_seconds=1200,
        )

        assert deleted == 2
        assert repo.by_token("pending-expired") is None
        assert repo.by_token("consumed-expired") is None
    finally:
        db.close()


def test_service_enforces_maximum_continuation_generation(tmp_path: Path):
    db_path = tmp_path / "depth.db"
    initialize_database(str(db_path))
    db = Database(str(db_path))
    service = ScanContinuationService(
        db=db,
        max_generation=4,
    )
    try:
        assert service.can_create_generation(4) is True
        assert service.can_create_generation(5) is False

        with pytest.raises(
            ContinuationDepthExceededError,
            match="maximum continuation chain depth",
        ):
            service.create(
                parent_run_id="depth-parent",
                lineage_root_run_id="depth-root",
                generation=5,
                symbols=["AAA"],
                request={},
            )
    finally:
        db.close()


def test_service_health_exposes_guardrail_policy(tmp_path: Path):
    db_path = tmp_path / "health.db"
    initialize_database(str(db_path))
    db = Database(str(db_path))
    service = ScanContinuationService(
        db=db,
        token_ttl_seconds=3600,
        stale_active_seconds=1200,
        max_generation=4,
        max_claim_attempts=3,
        cleanup_retention_seconds=86400,
    )
    try:
        health = service.health()
    finally:
        db.close()

    assert health["status"] == "ready"
    assert health["token_ttl_seconds"] == 3600
    assert health["stale_active_seconds"] == 1200
    assert health["max_generation"] == 4
    assert health["max_claim_attempts"] == 3
    assert health["cleanup_retention_seconds"] == 86400
    assert health["expired_records"] == 0
    assert health["exhausted_pending"] == 0
    assert health["stale_active"] == 0
