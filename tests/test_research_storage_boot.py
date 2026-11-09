"""Real database/file evidence distinguishes another call from another boot."""

import os
import sqlite3
from contextlib import closing

import pytest

from core.database import initialize_database
from services import research_storage_boot as boot
from services.cloud_paper_storage import PROOF_FILENAME


@pytest.fixture
def cloud_book(tmp_path, monkeypatch):
    database = tmp_path / "database" / "trendforge.db"
    initialize_database(str(database))
    monkeypatch.setenv("DATABASE_PATH", str(database))
    monkeypatch.setenv("TRENDFORGE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("TRENDFORGE_PERSISTENT_MOUNT", str(tmp_path))
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("TRENDFORGE_PAPER_TRADING_ENABLED", "false")
    monkeypatch.setattr(boot, "_BOOT_ID", "a" * 32)
    from core.storage_config import storage_health

    def mounted():
        report = storage_health()
        report["persistent_mount_is_mountpoint"] = True
        return report

    monkeypatch.setattr("services.cloud_paper_storage.storage_health", mounted)
    return database


def test_two_boot_recovery_preserves_rows_and_reports_and_never_enables_trading(
    cloud_book, monkeypatch
):
    report = cloud_book.parent.parent / "reports" / "research" / "evidence.csv"
    report.parent.mkdir(parents=True)
    report.write_bytes(b"symbol,entry,exit\nEXAMPLE,100,110\n")
    with closing(sqlite3.connect(cloud_book)) as db:
        db.execute("INSERT INTO settings(key,value) VALUES ('existing.report','keep')")
        db.commit()
    assert boot.verify_research_storage_boot() == "restart_required"
    assert boot.verify_research_storage_boot() == "restart_required"
    assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "false"
    monkeypatch.setattr(boot, "_BOOT_ID", "b" * 32)
    assert boot.verify_research_storage_boot() == "restart_verified"
    assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "true"
    with closing(sqlite3.connect(cloud_book)) as db:
        assert db.execute(
            "SELECT value FROM settings WHERE key='existing.report'"
        ).fetchone() == ("keep",)
    assert report.read_bytes() == b"symbol,entry,exit\nEXAMPLE,100,110\n"
    assert os.environ["TRENDFORGE_CLOUD_READ_ONLY"] == "true"
    assert os.environ["TRENDFORGE_LIVE_TRADING_ENABLED"] == "false"
    assert os.environ["TRENDFORGE_PAPER_TRADING_ENABLED"] == "false"


@pytest.mark.parametrize("damage", ["database", "proof", "mismatch"])
def test_damaged_evidence_cannot_inherit_operator_verification(
    cloud_book, monkeypatch, damage
):
    assert boot.verify_research_storage_boot() == "restart_required"
    proof = cloud_book.parent.parent / PROOF_FILENAME
    if damage == "database":
        cloud_book.unlink()
    elif damage == "proof":
        proof.unlink()
    else:
        proof.write_text("{}")
    before = cloud_book.read_bytes() if cloud_book.exists() else None
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    monkeypatch.setattr(boot, "_BOOT_ID", "b" * 32)
    assert boot.verify_research_storage_boot() == "unverified"
    assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "false"
    assert (cloud_book.read_bytes() if cloud_book.exists() else None) == before


@pytest.mark.parametrize(
    "key", ["TRENDFORGE_CLOUD_READ_ONLY", "TRENDFORGE_PRODUCTION_RUNTIME"]
)
def test_pc_and_nonproduction_books_are_untouched(cloud_book, monkeypatch, key):
    monkeypatch.setenv(key, "false")
    before = cloud_book.read_bytes()
    assert boot.verify_research_storage_boot() == "not_applicable"
    assert cloud_book.read_bytes() == before
    assert not (cloud_book.parent.parent / PROOF_FILENAME).exists()


def test_unconfigured_mount_does_not_assert_recovery(cloud_book, monkeypatch):
    monkeypatch.delenv("TRENDFORGE_PERSISTENT_MOUNT")
    assert boot.verify_research_storage_boot() == "not_configured"
    assert os.environ["TRENDFORGE_STORAGE_RECOVERY_VERIFIED"] == "false"
