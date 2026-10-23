"""Failed paper recovery blocks new entry until recovery actually succeeds."""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from types import SimpleNamespace

import pytest

from services.paper_trading_service import PaperTradingService, PaperTradingStorageError

SECRET = secrets.token_hex(16)


class Runtime:
    def __init__(self):
        self.fail_restore = True
        self.open_calls = []
        self.monitor_calls = []
        self.exit_calls = []
        self.portfolio = SimpleNamespace(positions={})

    def load_kill_switch(self):
        return False

    def save_kill_switch(self, enabled):
        return True

    def restore_open(self):
        if self.fail_restore:
            raise ValueError(f"Invalid stored position: {SECRET}")
        return 2

    def open(self, order, now=None):
        self.open_calls.append(order)
        return 1

    def snapshot(self):
        return {"positions": [], "open_positions": 0}

    def monitor(self, quotes, now=None):
        self.monitor_calls.append(quotes)
        return []

    def close_strategy_exit(self, symbol, exit_price, **kwargs):
        self.exit_calls.append(symbol)
        return {"symbol": symbol, "exit_price": exit_price}


@pytest.fixture
def paper(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "true")
    monkeypatch.setattr(
        "core.paper_storage_policy.storage_health",
        lambda: {"verified_persistent": True},
    )
    return PaperTradingService(Runtime(), enabled=True, environment_kill_switch=False)


def order():
    return SimpleNamespace(
        symbol="TCS", side="BUY", quantity=1, price=100.0, stoploss=95.0, target2=110.0
    )


def fail_restore(paper):
    with pytest.raises(RuntimeError, match="Paper position restoration is unavailable"):
        paper.restore_open()


def test_failed_restore_blocks_entry_readiness_and_snapshot_without_leaking_error(
    paper, caplog
):
    assert paper.can_open_new_positions is True
    fail_restore(paper)

    assert paper.can_open_new_positions is False
    health = paper.health()
    snapshot = paper.snapshot()
    assert health["can_open_new_positions"] is False
    assert snapshot["can_open_new_positions"] is False
    assert health["entry_storage_policy"]["reason"] == "position_restore_unavailable"
    assert health["position_restore"]["status"] == "unavailable"
    reference = health["position_restore"]["reference"]
    assert len(reference) == 12
    assert reference in caplog.text
    with pytest.raises(PaperTradingStorageError) as error:
        paper.open(order(), now=datetime(2026, 10, 23, 10, 0))
    assert paper.runtime.open_calls == []
    assert SECRET not in str(error.value)
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps({"health": health, "snapshot": snapshot})


def test_clearing_kill_cannot_release_failed_restore_gate(paper):
    fail_restore(paper)
    paper.set_runtime_kill_switch(True)
    cleared = paper.set_runtime_kill_switch(False)
    assert cleared["kill_switch"] is False
    assert cleared["can_open_new_positions"] is False
    assert cleared["position_restore"]["status"] == "unavailable"
    with pytest.raises(PaperTradingStorageError):
        paper.open(order())
    assert paper.runtime.open_calls == []


def test_restore_gate_preserves_monitoring_exits_and_emergency_kill(paper):
    fail_restore(paper)
    assert paper.monitor({"TCS": 105.0})["status"] == "monitored"
    assert (
        paper.close_strategy_exit("TCS", 105.0, exit_signal="SELL")["status"]
        == "closed"
    )
    assert paper.set_runtime_kill_switch(True)["kill_switch"] is True
    assert paper.runtime.monitor_calls == [{"TCS": 105.0}]
    assert paper.runtime.exit_calls == ["TCS"]
    assert paper.can_open_new_positions is False


def test_failed_restore_retry_stays_blocked_until_successful_recovery(paper):
    fail_restore(paper)
    fail_restore(paper)
    assert paper.can_open_new_positions is False
    paper.runtime.fail_restore = False

    assert paper.restore_open() == 2

    assert paper.health()["position_restore"] == {
        "status": "restored",
        "open_trades": 2,
    }
    assert paper.can_open_new_positions is True
    assert paper.snapshot()["can_open_new_positions"] is True
    result = paper.open(order())
    assert result["status"] == "opened"
    assert len(paper.runtime.open_calls) == 1
