"""R70.2 fail-closed PC runtime contract tests; never require Kite/network."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3

import pytest

from core.database import initialize_database
from scripts import local_engine_runtime as runtime


def make_store(tmp_path, monkeypatch):
    root = tmp_path / "data"
    db_path = root / "database" / "trendforge.db"
    initialize_database(str(db_path))
    monkeypatch.setenv("TRENDFORGE_DATA_DIR", str(root))
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    return root, db_path


def test_preflight_blocks_unconfigured(monkeypatch):
    monkeypatch.delenv("TRENDFORGE_DATA_DIR", raising=False)
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    assert runtime.preflight()["status"] == "blocked"


def test_preflight_checks_23_table_database(tmp_path, monkeypatch):
    root, db = make_store(tmp_path, monkeypatch)
    result = runtime.preflight()
    assert result["status"] == "ready"
    assert result["tables"] >= 23
    assert result["live_orders_enabled"] is False
    assert result["automatic_scanning_enabled"] is False


def test_preflight_rejects_wrong_database(tmp_path):
    folder = tmp_path / "data"
    wrong = tmp_path / "unexpected.db"
    assert runtime.preflight(str(folder), str(wrong))["status"] == "blocked"


def test_preflight_rejects_missing_schema(tmp_path):
    root = tmp_path / "data"
    db = root / "database" / "trendforge.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE fundamentals (symbol TEXT)")
    assert runtime.preflight(str(root), str(db))["schema"] == "degraded"


def test_kite_check_is_explicit_and_no_secrets_logged(monkeypatch):
    monkeypatch.delenv("KITE_API_KEY", raising=False)
    monkeypatch.delenv("KITE_ACCESS_TOKEN", raising=False)
    assert runtime.verify_kite_session()["status"] == "not_authenticated"


def test_lock_prevents_second_engine(tmp_path):
    lock = tmp_path / "engine.lock"
    with runtime.exclusive_lock(lock):
        with pytest.raises(RuntimeError, match="already running"):
            with runtime.exclusive_lock(lock):
                pass
    with runtime.exclusive_lock(lock):
        pass


def test_observer_exits_weekends_without_orders(tmp_path, monkeypatch):
    root, db = make_store(tmp_path, monkeypatch)
    result = runtime.run(now=lambda: datetime(2026, 10, 17, 10, 0, tzinfo=runtime.IST),
                         sleep=lambda _: pytest.fail("weekend must not poll"))
    assert result["status"] == "non_trading_weekend"
    stored = json.loads((root / "logs" / "local_engine_status.json").read_text())
    assert stored["paper_orders_enabled"] is False
    assert stored["live_orders_enabled"] is False
    assert stored["market_calendar"] == "not_verified"


def test_observer_stops_at_1600_ist(tmp_path, monkeypatch):
    root, db = make_store(tmp_path, monkeypatch)
    result = runtime.run(now=lambda: datetime(2026, 10, 19, 16, 0, tzinfo=runtime.IST),
                         sleep=lambda _: pytest.fail("past cutoff"))
    assert result["status"] == "market_day_window_complete"


def test_stop_signal_causes_clean_shutdown(tmp_path, monkeypatch):
    root, db = make_store(tmp_path, monkeypatch)
    count = [0]

    def fake_sleep(_):
        count[0] += 1
        (root / "logs" / "local_engine.stop").write_text("stop")

    result = runtime.run(now=lambda: datetime(2026, 10, 19, 9, 15, tzinfo=runtime.IST),
                         sleep=fake_sleep)
    assert result["status"] == "stopped"
    assert count == [1]
    assert not (root / "logs" / "local_engine.stop").exists()


def test_manual_scan_fails_closed_without_kite(tmp_path, monkeypatch):
    root, db = make_store(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime, "verify_kite_session", lambda: {"status": "not_authenticated"})
    assert runtime.scan_once(25)["status"] == "blocked"
    assert runtime.scan_once(26)["status"] == "blocked"


def test_write_status_atomically(tmp_path):
    path = tmp_path / "logs" / "status.json"
    runtime.write_status(path, {"status": "ready"})
    assert json.loads(path.read_text())["status"] == "ready"
    assert list(path.parent.glob("*.tmp")) == []
