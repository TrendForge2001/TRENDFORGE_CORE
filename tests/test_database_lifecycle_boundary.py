from __future__ import annotations
import sqlite3
from core.database import initialize_database
def test_database_initialization_creates_schema_in_temp_path(tmp_path):
    path = tmp_path / "trendforge.db"
    result = initialize_database(str(path))
    assert result["status"] == "initialized"
    assert result["path"] == str(path)
    assert result["migrations"] > 0
    connection = sqlite3.connect(path)
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    connection.close()
    assert tables


def test_database_default_path_is_not_created_on_module_import(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import importlib
    import core.database as database_module
    importlib.reload(database_module)
    assert not (tmp_path / "database" / "trendforge.db").exists()
