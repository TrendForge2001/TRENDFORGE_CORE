"""Paper service recovery keeps entry locks and emergency exits independent."""
from __future__ import annotations

from datetime import datetime
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from database.database import Database
from database.migrations import settings, trade_history
from database.repositories.trade_repository import TradeRepository
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import PaperTradingKillSwitchError, PaperTradingService


MARKET_TIME = datetime(2026, 9, 18, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
SECRET = "PAPER_CONTROL_SECRET_MUST_NOT_APPEAR"


def configure_production(monkeypatch, path):
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "true")
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.delenv("TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION", raising=False)
    # This is policy integration using a temporary file, not a claim that /tmp
    # passed a real persistent-mount or cloud-restart acceptance check.
    monkeypatch.setattr(
        "core.paper_storage_policy.storage_health", lambda: {"verified_persistent": True},
    )


def initialize(database):
    settings.migrate(database)
    trade_history.migrate(database)


def service_for(database):
    return PaperTradingService(
        PaperTradingRuntime(trades=TradeRepository(database)),
        enabled=True,
        environment_kill_switch=False,
    )


def order(symbol="TCS"):
    return SimpleNamespace(
        symbol=symbol, side="BUY", quantity=1, price=1000.0,
        stoploss=900.0, target2=1200.0, trade_mode="swing",
        strategy_id="test_strategy", strategy_name="Fixture strategy",
    )


def test_persisted_kill_recovers_positions_and_preserves_exits_when_storage_blocks(monkeypatch, tmp_path):
    path = tmp_path / "paper.db"
    configure_production(monkeypatch, path)
    with Database(str(path)) as database:
        initialize(database)
        service = service_for(database)
        assert service.can_open_new_positions is True
        service.open(order("TCS"), now=MARKET_TIME)
        service.open(order("INFY"), now=MARKET_TIME)
        killed = service.set_runtime_kill_switch(True)
        assert killed["runtime_kill_switch"] is True
        assert killed["kill_switch_storage"]["status"] == "persisted"

    with Database(str(path)) as database:
        recovered = service_for(database)
        assert recovered.runtime_kill_switch is True
        assert recovered.restore_open() == 2
        assert recovered.can_open_new_positions is False
        monkeypatch.setattr(
            "core.paper_storage_policy.storage_health", lambda: {"verified_persistent": False},
        )
        assert recovered.health()["entry_storage_policy"]["mode"] == "blocked"
        with pytest.raises(PaperTradingKillSwitchError):
            recovered.open(order("SBIN"), now=MARKET_TIME)
        assert len(recovered.runtime.trades.open_trades()) == 2

        target_exit = recovered.monitor({"TCS": 1200.0}, now=MARKET_TIME)
        assert target_exit["closed"][0]["reason"] == "TARGET"
        strategy_exit = recovered.close_strategy_exit(
            "INFY", 1100.0, exit_signal="SELL", now=MARKET_TIME,
        )
        assert strategy_exit["closed"]["reason"] == "STRATEGY_EXIT"
        assert recovered.runtime.trades.open_trades() == []
        assert len(recovered.runtime.trades.closed_trades()) == 2
        assert recovered.set_runtime_kill_switch(True)["runtime_kill_switch"] is True


@pytest.mark.parametrize("failure", ["corrupt", "unreadable"])
def test_unreadable_kill_state_locks_entries_with_safe_health_and_logs(monkeypatch, tmp_path, caplog, failure):
    path = tmp_path / "paper.db"
    configure_production(monkeypatch, path)
    with Database(str(path)) as database:
        initialize(database)
        if failure == "corrupt":
            database.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?)",
                (PaperTradingRuntime.KILL_SWITCH_SETTING, SECRET),
            )
        else:
            original_fetchone = database.fetchone

            def fail_control_read(query, params=()):
                if "FROM settings" in query:
                    raise RuntimeError(SECRET)
                return original_fetchone(query, params)

            monkeypatch.setattr(database, "fetchone", fail_control_read)
        service = service_for(database)
        health = service.health()

        assert health["status"] == "locked"
        assert health["kill_switch"] is True
        assert health["can_open_new_positions"] is False
        assert health["kill_switch_storage"]["status"] == "unavailable"
        assert health["entry_storage_policy"]["reason"] == "kill_control_storage_unavailable"
        reference = health["kill_switch_storage"]["reference"]
        assert len(reference) == 12
        assert reference in caplog.text
        assert SECRET not in json.dumps(health)
        assert SECRET not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
        with pytest.raises(PaperTradingKillSwitchError):
            service.open(order(), now=MARKET_TIME)
        assert service.runtime.trades.open_trades() == []


@pytest.mark.parametrize("already_killed", [False, True])
def test_failed_kill_write_stays_locked_and_reports_unavailable(monkeypatch, tmp_path, already_killed):
    path = tmp_path / "paper.db"
    configure_production(monkeypatch, path)
    with Database(str(path)) as database:
        initialize(database)
        service = service_for(database)
        if already_killed:
            service.set_runtime_kill_switch(True)
        database.execute("PRAGMA query_only = ON")

        health = service.set_runtime_kill_switch(not already_killed)

        assert health["runtime_kill_switch"] is True
        assert health["kill_switch_storage"]["status"] == "unavailable"
        assert health["can_open_new_positions"] is False
        assert health["entry_storage_policy"]["reason"] == "kill_control_storage_unavailable"
        row = database.fetchone(
            "SELECT value FROM settings WHERE key = ?",
            (PaperTradingRuntime.KILL_SWITCH_SETTING,),
        )
        assert (row["value"] if row else None) == ("true" if already_killed else None)


def test_clear_keeps_memory_kill_until_database_commit_is_visible(monkeypatch, tmp_path):
    path = tmp_path / "paper.db"
    configure_production(monkeypatch, path)
    with Database(str(path)) as database:
        initialize(database)
        service = service_for(database)
        service.set_runtime_kill_switch(True)
        original_save = service.runtime.save_kill_switch
        calls = []

        def observe_clear(enabled):
            assert enabled is False
            assert service.runtime_kill_switch is True
            result = original_save(enabled)
            with Database(str(path)) as independent_reader:
                assert PaperTradingRuntime(trades=TradeRepository(independent_reader)).load_kill_switch() is False
            assert service.runtime_kill_switch is True
            calls.append(enabled)
            return result

        monkeypatch.setattr(service.runtime, "save_kill_switch", observe_clear)
        health = service.set_runtime_kill_switch(False)

        assert calls == [False]
        assert health["runtime_kill_switch"] is False
        assert health["kill_switch_storage"]["status"] == "persisted"
        assert health["can_open_new_positions"] is True
