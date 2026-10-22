"""Repositories and paper runtime must use the database reported by diagnostics."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from core.database import database_path, initialize_database
from core.storage_config import SUBDIRECTORIES, resolve_storage
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from services.paper_trading_runtime import PaperTradingRuntime


def _configure_data_dir(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    root = tmp_path / "local-data"
    monkeypatch.setenv("TRENDFORGE_DATA_DIR", str(root))
    return root, root / "database" / "trendforge.db"


def test_default_repository_writes_to_canonical_data_directory(monkeypatch, tmp_path):
    root, expected = _configure_data_dir(monkeypatch, tmp_path)
    initialize_database()
    repository = TradeRepository()
    try:
        assert repository.db.db_path == database_path() == str(expected)
        repository.save(
            symbol="TCS", side="BUY", quantity=1, entry_price=3000.0,
            stoploss=2950.0, target=3100.0,
        )
        with sqlite3.connect(expected) as connection:
            assert connection.execute("SELECT symbol FROM trade_history").fetchone()[0] == "TCS"
        active = repository.db.fetchone("PRAGMA database_list")
        assert Path(active["file"]) == expected.resolve()
    finally:
        repository.close()

    assert not (tmp_path / "database").exists()
    assert all(not (root / name).exists() for name in SUBDIRECTORIES if name != "database")


def test_default_paper_runtime_persists_into_same_database(monkeypatch, tmp_path):
    _, expected = _configure_data_dir(monkeypatch, tmp_path)
    initialize_database()
    runtime = PaperTradingRuntime()
    try:
        order = SimpleNamespace(
            symbol="TCS", side="BUY", quantity=1, price=3000.0,
            stoploss=2950.0, target2=3100.0,
        )
        trade_id = runtime.open(order, now=datetime(2026, 9, 18, 10, 0))
        with sqlite3.connect(expected) as connection:
            row = connection.execute(
                "SELECT symbol, status FROM trade_history WHERE id=?", (trade_id,),
            ).fetchone()
        assert row == ("TCS", "OPEN")
        assert runtime.trades.db.db_path == database_path()
    finally:
        runtime.close()


def test_database_environment_override_wins_without_creating_data_directory(monkeypatch, tmp_path):
    root, _ = _configure_data_dir(monkeypatch, tmp_path)
    override = tmp_path / "configured" / "existing.db"
    monkeypatch.setenv("DATABASE_PATH", str(override))
    with Database() as database:
        assert database.db_path == database_path() == str(override)
        database.execute("CREATE TABLE preservation (value INTEGER)")
        database.execute("INSERT INTO preservation VALUES (7)")
    with Database() as database:
        assert database.fetchone("SELECT value FROM preservation")["value"] == 7
    assert not root.exists()


def test_explicit_constructor_wins_over_both_environment_paths(monkeypatch, tmp_path):
    root, _ = _configure_data_dir(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "unused-env" / "unused.db"))
    explicit = tmp_path / "explicit" / "selected.db"
    with Database(str(explicit)) as database:
        database.execute("CREATE TABLE selected (value INTEGER)")
        assert database.db_path == str(explicit)
        assert database.fetchone("PRAGMA database_list")["file"] == str(explicit)
    assert not root.exists()
    assert not (tmp_path / "unused-env").exists()


@pytest.mark.parametrize("source", ["constructor", "environment"])
def test_in_memory_database_remains_in_memory(monkeypatch, tmp_path, source):
    root, _ = _configure_data_dir(monkeypatch, tmp_path)
    if source == "environment":
        monkeypatch.setenv("DATABASE_PATH", ":memory:")
    with Database(":memory:" if source == "constructor" else None) as database:
        database.execute("CREATE TABLE transient (value INTEGER)")
        assert database.db_path == ":memory:"
        assert database.fetchone("PRAGMA database_list")["file"] == ""
    assert not root.exists()
    assert list(tmp_path.iterdir()) == []


def test_legacy_default_remains_relative_and_preserves_existing_rows(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("TRENDFORGE_DATA_DIR", raising=False)
    with Database() as database:
        assert database.db_path == str(resolve_storage().database) == "database/trendforge.db"
        database.execute("CREATE TABLE retained (value INTEGER)")
        database.execute("INSERT INTO retained VALUES (11)")
    with Database() as database:
        assert database.fetchone("SELECT value FROM retained")["value"] == 11
    assert sorted(path.name for path in tmp_path.iterdir()) == ["database"]
