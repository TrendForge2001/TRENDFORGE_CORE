from __future__ import annotations

import sqlite3

from core.database import database_health, initialize_database


def test_database_initialization_creates_schema_in_temp_path(tmp_path):
    path = tmp_path / "trendforge.db"
    result = initialize_database(str(path))
    assert result["status"] == "initialized"
    assert result["path"] == str(path)
    assert result["migrations"] > 0

    health = database_health(str(path))
    assert health["status"] == "ready"
    assert health["integrity_check"] == "ok"
    assert health["tables"] >= result["migrations"]

    connection = sqlite3.connect(path)
    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    connection.close()
    assert tables


def test_database_default_path_is_not_created_on_module_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    import core.database as database_module

    importlib.reload(database_module)
    assert not (tmp_path / "database" / "trendforge.db").exists()


def test_database_health_rejects_existing_but_uninitialized_sqlite_file(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()

    health = database_health(str(path))

    assert health["status"] == "degraded"
    assert health["reason"] == "schema_incomplete"
    assert "instruments" in health["missing_tables"]


def test_database_health_rejects_corrupt_database_file(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"not a sqlite database")

    health = database_health(str(path))

    assert health["status"] == "degraded"
    assert health["reason"] == "database_unreadable"
