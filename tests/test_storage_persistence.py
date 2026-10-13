from __future__ import annotations

from pathlib import Path

from core.database import initialize_database
from services.storage_persistence_service import StoragePersistenceService


def test_storage_identity_survives_reopen_and_boot_count_increments(tmp_path: Path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    first = StoragePersistenceService(db_path=str(db_path))
    try:
        first_boot = first.record_boot(
            git_commit="commit-a",
            service_id="srv-test",
        )
    finally:
        first.close()

    second = StoragePersistenceService(db_path=str(db_path))
    try:
        second_boot = second.record_boot(
            git_commit="commit-b",
            service_id="srv-test",
        )
        health = second.health()
    finally:
        second.close()

    assert first_boot["status"] == "recorded"
    assert second_boot["status"] == "recorded"
    assert first_boot["storage_id"] == second_boot["storage_id"]
    assert first_boot["boot_count"] == 1
    assert second_boot["boot_count"] == 2
    assert second_boot["last_git_commit"] == "commit-b"
    assert health["status"] == "ready"
    assert health["storage_id"] == first_boot["storage_id"]
    assert health["boot_count"] == 2


def test_storage_identity_is_unique_per_fresh_database(tmp_path: Path):
    path_a = tmp_path / "a.db"
    path_b = tmp_path / "b.db"
    initialize_database(str(path_a))
    initialize_database(str(path_b))

    service_a = StoragePersistenceService(db_path=str(path_a))
    service_b = StoragePersistenceService(db_path=str(path_b))
    try:
        state_a = service_a.record_boot()
        state_b = service_b.record_boot()
    finally:
        service_a.close()
        service_b.close()

    assert state_a["storage_id"] != state_b["storage_id"]
