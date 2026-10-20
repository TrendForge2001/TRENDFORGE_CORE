"""R70.1 isolation, preservation and SQLite backup behavior."""
import sqlite3

import pytest

from core.storage_config import resolve_storage, initialize_directories
from services.local_storage_service import verify_database, backup_database, migrate_database


def test_legacy_database_path_unchanged():
    config = resolve_storage({})
    assert str(config.database).replace("\\", "/") == "database/trendforge.db"


def test_local_root_opt_in(tmp_path):
    config = resolve_storage({"TRENDFORGE_DATA_DIR": str(tmp_path)})
    assert config.database == tmp_path / "database" / "trendforge.db"
    assert not (tmp_path / "database").exists()
    initialize_directories(config, create=True)
    assert (tmp_path / "backups").is_dir()


def test_explicit_database_path_wins(tmp_path):
    config = resolve_storage({"TRENDFORGE_DATA_DIR": str(tmp_path),
                              "DATABASE_PATH": "database/original.db"})
    assert str(config.database).replace("\\", "/") == "database/original.db"


def test_backup_preserves_rows_and_source(tmp_path):
    original = tmp_path / "original.db"
    with sqlite3.connect(original) as db:
        db.execute("CREATE TABLE fundamentals (symbol TEXT)")
        db.execute("INSERT INTO fundamentals VALUES ('BSE')")
    target = tmp_path / "backup.db"
    result = backup_database(original, target)
    assert result["status"] == "verified"
    assert verify_database(target)["status"] == "ok"
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT symbol FROM fundamentals").fetchone()[0] == "BSE"
    assert original.exists()
    with pytest.raises(FileExistsError):
        migrate_database(original, target)


def test_corrupt_and_missing_rejected(tmp_path):
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not sqlite")
    assert verify_database(broken)["status"] == "error"
    assert verify_database(tmp_path / "missing.db")["status"] == "missing"
    with pytest.raises(ValueError):
        backup_database(broken, tmp_path / "target.db")


def test_backup_closes_connections_and_removes_temp_files(tmp_path):
    original = tmp_path / "wal_source.db"
    with sqlite3.connect(original) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, qty INTEGER)")
        db.execute("INSERT INTO positions(qty) VALUES (12)")
    target = tmp_path / "verified_backup.db"
    result = backup_database(original, target)
    assert result["status"] == "verified"
    assert list(tmp_path.glob(".trendforge-backup-*")) == []
    with sqlite3.connect(target) as db:
        assert db.execute("SELECT qty FROM positions").fetchone()[0] == 12
