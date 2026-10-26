"""Real SQLite restart evidence plus strict mounted-disk admission."""

import json
import sqlite3
from contextlib import closing

import pytest

from core.database import initialize_database
from services.cloud_paper_storage import (
    PROBE_KEY,
    PROOF_FILENAME,
    prepare_cloud_storage,
)


@pytest.fixture
def book(tmp_path, monkeypatch):
    database = tmp_path / "book.db"
    initialize_database(str(database))
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("TRENDFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRENDFORGE_PERSISTENT_MOUNT", str(tmp_path))
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    from core import storage_config

    original = storage_config.storage_health

    def mounted():
        report = original()
        # Only infrastructure is simulated; real DB/file recovery is exercised.
        report["persistent_mount_is_mountpoint"] = True
        return report

    monkeypatch.setattr("services.cloud_paper_storage.storage_health", mounted)
    return database


def test_first_boot_blocks_then_later_boot_preserves_book_and_verifies(book):
    with closing(sqlite3.connect(book)) as db:
        db.execute("INSERT INTO settings(key,value) VALUES ('test.ledger','preserve')")
        db.commit()
    assert prepare_cloud_storage(boot_id="a" * 32) is False
    assert prepare_cloud_storage(boot_id="a" * 32) is False
    assert prepare_cloud_storage(boot_id="b" * 32) is True
    with closing(sqlite3.connect(book)) as db:
        assert db.execute(
            "SELECT value FROM settings WHERE key='test.ledger'"
        ).fetchone() == ("preserve",)


@pytest.mark.parametrize(
    "damage",
    ["missing_database", "missing_file", "missing_row", "mismatch", "oversized"],
)
def test_lost_or_mismatched_evidence_never_replaces_book(book, damage):
    prepare_cloud_storage(boot_id="a" * 32)
    proof = book.parent / PROOF_FILENAME
    if damage == "missing_database":
        book.unlink()
    elif damage == "missing_file":
        proof.unlink()
    elif damage == "missing_row":
        with closing(sqlite3.connect(book)) as db:
            db.execute("DELETE FROM settings WHERE key=?", (PROBE_KEY,))
            db.commit()
    elif damage == "oversized":
        proof.write_text("x" * 4097)
    else:
        value = json.loads(proof.read_text())
        value["nonce"] = "0" * 64
        proof.write_text(json.dumps(value))
    before = book.read_bytes() if book.exists() else None
    with pytest.raises(ValueError):
        prepare_cloud_storage(boot_id="b" * 32)
    assert (book.read_bytes() if book.exists() else None) == before


def test_real_unmounted_path_is_rejected_despite_operator_flag(book, monkeypatch):
    from core.storage_config import storage_health

    monkeypatch.setattr("services.cloud_paper_storage.storage_health", storage_health)
    with pytest.raises(ValueError, match="mounted"):
        prepare_cloud_storage(boot_id="a" * 32)
    assert not (book.parent / PROOF_FILENAME).exists()


def test_missing_book_is_not_created(book):
    book.unlink()
    with pytest.raises(ValueError):
        prepare_cloud_storage(boot_id="a" * 32)
    assert not book.exists()


def test_book_disappearing_after_inspection_is_not_recreated(book, monkeypatch):
    def disappear(_path):
        book.unlink()
        return {"status": "ok"}

    monkeypatch.setattr("services.cloud_paper_storage.verify_database", disappear)
    with pytest.raises(sqlite3.Error):
        prepare_cloud_storage(boot_id="a" * 32)
    assert not book.exists()


def test_data_root_outside_mount_rejected(book, monkeypatch, tmp_path):
    monkeypatch.setenv("TRENDFORGE_DATA_DIR", str(tmp_path.parent))
    with pytest.raises(ValueError, match="data directory"):
        prepare_cloud_storage(boot_id="a" * 32)


def test_launcher_ignores_operator_recovery_and_ephemeral_bypasses(book, monkeypatch):
    from scripts.render_paper_runtime import configure_storage

    monkeypatch.setenv("TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION", "true")
    monkeypatch.setenv("TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES", "true")
    assert configure_storage() is False
    import os

    for name in (
        "TRENDFORGE_STORAGE_RECOVERY_VERIFIED",
        "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION",
        "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES",
    ):
        assert os.environ[name] == "false"
    assert configure_storage() is True


def test_corrupt_database_and_invalid_boot_id_fail_closed(book):
    with pytest.raises(ValueError):
        prepare_cloud_storage(boot_id="operator-confirmed")
    book.write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        prepare_cloud_storage(boot_id="a" * 32)


def test_server_holds_one_book_lock_for_its_entire_lifetime(book, monkeypatch):
    import uvicorn

    from scripts.local_engine_runtime import exclusive_lock
    from scripts.render_paper_runtime import main

    calls = []
    monkeypatch.setenv("PORT", "10000")

    def serve(*args, **kwargs):
        calls.append((args, kwargs))
        with (
            pytest.raises(RuntimeError),
            exclusive_lock(book.parent / "paper-cloud-runtime.lock"),
        ):
            pytest.fail("A second server acquired the book")

    monkeypatch.setattr(uvicorn, "run", serve)
    assert main() == 0
    assert calls == [(("start:app",), {"host": "0.0.0.0", "port": 10000, "workers": 1})]
    with exclusive_lock(book.parent / "paper-cloud-runtime.lock"):
        pass
