from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.paper_trading_service import (
    PaperTradingDisabledError,
    PaperTradingKillSwitchError,
    PaperTradingService,
)


class FakeRuntime:
    def __init__(self):
        self.restore_calls = 0
        self.open_calls = []
        self.monitor_calls = []
        self.closed = False

    def restore_open(self):
        self.restore_calls += 1
        return 2

    def open(self, order, now=None):
        self.open_calls.append((order, now))
        return 17

    def monitor(self, quotes, now=None):
        self.monitor_calls.append((dict(quotes), now))
        return [{"symbol": "TCS", "reason": "TARGET"}]

    def snapshot(self):
        return {
            "open_positions": 1,
            "positions": [{"symbol": "TCS"}],
            "unrealized_pnl": 25.0,
            "realized_pnl": 10.0,
            "total_pnl": 35.0,
        }

    def close(self):
        self.closed = True


def order():
    return SimpleNamespace(
        symbol="TCS",
        side="BUY",
        quantity=1,
        price=3000.0,
        stoploss=2950.0,
        target2=3100.0,
    )


def test_service_is_fail_closed_when_disabled():
    runtime = FakeRuntime()
    service = PaperTradingService(
        runtime,
        enabled=False,
        environment_kill_switch=False,
    )

    with pytest.raises(PaperTradingDisabledError):
        service.open(order())

    assert runtime.open_calls == []
    assert service.health()["status"] == "disabled"
    assert service.health()["broker_orders_allowed"] is False


def test_environment_kill_switch_blocks_new_entries():
    runtime = FakeRuntime()
    service = PaperTradingService(
        runtime,
        enabled=True,
        environment_kill_switch=True,
    )

    with pytest.raises(PaperTradingKillSwitchError):
        service.open(order())

    service.set_runtime_kill_switch(False)
    assert service.kill_switch is True
    assert service.can_open_new_positions is False
    assert runtime.open_calls == []


def test_enabled_service_opens_only_paper_runtime():
    runtime = FakeRuntime()
    service = PaperTradingService(
        runtime,
        enabled=True,
        environment_kill_switch=False,
    )

    result = service.open(order())

    assert result["status"] == "opened"
    assert result["trade_id"] == 17
    assert result["mode"] == "paper_only"
    assert result["broker_orders_allowed"] is False
    assert result["can_open_new_positions"] is True
    assert len(runtime.open_calls) == 1


def test_monitor_remains_available_while_entries_are_killed():
    runtime = FakeRuntime()
    service = PaperTradingService(
        runtime,
        enabled=True,
        environment_kill_switch=True,
    )

    result = service.monitor({"tcs": 3100})

    assert result["status"] == "monitored"
    assert result["closed"][0]["reason"] == "TARGET"
    assert runtime.monitor_calls[0][0] == {"TCS": 3100.0}


def test_restore_health_and_close_lifecycle():
    runtime = FakeRuntime()
    service = PaperTradingService(
        runtime,
        enabled=True,
        environment_kill_switch=False,
    )

    assert service.restore_open() == 2
    health = service.health()
    assert health["status"] == "ready"
    assert health["restored_open_trades"] == 2
    assert health["market_open_time_ist"] == "09:15"
    assert health["force_exit_time_ist"] == "15:00"

    service.close()
    assert runtime.closed is True
