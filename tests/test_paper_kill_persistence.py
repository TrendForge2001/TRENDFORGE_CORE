"""Paper kill state shares trade storage and survives connection replacement."""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from database.database import Database
from database.migrations.settings import migrate
from database.repositories.trade_repository import TradeRepository
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingService


def runtime_for(database: Database) -> PaperTradingRuntime:
    return PaperTradingRuntime(trades=TradeRepository(database))


def test_kill_state_survives_database_close_and_reopen(tmp_path):
    path = str(tmp_path / "paper.db")
    with Database(path) as database:
        migrate(database)
        runtime = runtime_for(database)
        assert runtime.load_kill_switch() is False
        assert runtime.save_kill_switch(True) is True

    with Database(path) as database:
        runtime = runtime_for(database)
        assert runtime.load_kill_switch() is True
        assert runtime.save_kill_switch(False) is True

    with Database(path) as database:
        assert runtime_for(database).load_kill_switch() is False
        assert database.fetchone("SELECT COUNT(*) AS total FROM settings")["total"] == 1


def test_successful_save_is_committed_for_independent_connection(tmp_path):
    path = str(tmp_path / "paper.db")
    with Database(path) as writer, Database(path) as reader:
        migrate(writer)
        runtime = runtime_for(writer)
        assert runtime.save_kill_switch(True) is True
        assert runtime_for(reader).load_kill_switch() is True


def test_legacy_injected_repository_reports_no_persistence_support():
    runtime = PaperTradingRuntime(trades=SimpleNamespace())
    assert runtime.load_kill_switch() is None
    assert runtime.save_kill_switch(True) is False


@pytest.mark.parametrize("method", ["load", "save"])
def test_missing_settings_table_propagates_database_failure(tmp_path, method):
    with Database(str(tmp_path / "uninitialized.db")) as database:
        runtime = runtime_for(database)
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            if method == "load":
                runtime.load_kill_switch()
            else:
                runtime.save_kill_switch(True)


@pytest.mark.parametrize("invalid", ["true-with-secret-token", "1", "", None])
def test_invalid_stored_state_raises_without_echoing_value(tmp_path, invalid):
    with Database(str(tmp_path / "paper.db")) as database:
        migrate(database)
        runtime = runtime_for(database)
        database.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?)",
            (runtime.KILL_SWITCH_SETTING, invalid),
        )
        with pytest.raises(ValueError) as error:
            runtime.load_kill_switch()
        assert str(error.value) == "Stored paper kill-switch state is invalid"


def test_failed_write_does_not_claim_success_or_clear_existing_kill(tmp_path):
    path = str(tmp_path / "paper.db")
    with Database(path) as database:
        migrate(database)
        runtime = runtime_for(database)
        assert runtime.save_kill_switch(True) is True
        database.execute("PRAGMA query_only = ON")
        with pytest.raises(sqlite3.OperationalError):
            runtime.save_kill_switch(False)
        assert runtime.load_kill_switch() is True

    with Database(path) as database:
        assert runtime_for(database).load_kill_switch() is True


def test_failed_kill_clear_commit_cannot_be_committed_by_later_database_work(tmp_path):
    """SQLite busy on commit must roll back the attempted saved un-kill."""
    path = str(tmp_path / "paper.db")
    with Database(path) as writer:
        migrate(writer)
        runtime = runtime_for(writer)
        runtime.save_kill_switch(True)
        service = PaperTradingService(runtime, enabled=True, environment_kill_switch=False)
        # A second connection holds a read lock. SQLite permits the UPDATE but
        # refuses its commit, leaving a pending transaction unless rolled back.
        writer.conn.execute("PRAGMA busy_timeout = 1")
        reader = sqlite3.connect(path)
        try:
            reader.execute("BEGIN")
            reader.execute("SELECT value FROM settings").fetchone()
            result = service.set_runtime_kill_switch(False)
            assert result["runtime_kill_switch"] is True
            assert result["kill_switch_storage"]["status"] == "unavailable"
            assert writer.conn.in_transaction is False
        finally:
            reader.rollback()
            reader.close()

        # Subsequent observational and write calls must not accidentally commit
        # the failed clear after the external reader releases its lock.
        writer.fetchone("SELECT 1")
        writer.execute("CREATE TABLE unrelated_work (value INTEGER)")
        writer.execute("INSERT INTO unrelated_work VALUES (7)")
        with Database(path) as independent_reader:
            assert runtime_for(independent_reader).load_kill_switch() is True

    with Database(path) as reopened:
        assert runtime_for(reopened).load_kill_switch() is True
        assert reopened.fetchone("SELECT value FROM unrelated_work")["value"] == 7
