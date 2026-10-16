from __future__ import annotations

from types import SimpleNamespace

from services.paper_trading_service import PaperTradingService


class Runtime:
    def __init__(self):
        self.open_calls = []
        self.monitor_calls = []

    def open(self, order, now=None):
        self.open_calls.append((order, now))
        return 41

    def monitor(self, quotes, now=None):
        self.monitor_calls.append((dict(quotes), now))
        return [
            {
                "trade_id": 41,
                "symbol": "TCS",
                "exit_price": 3100.0,
                "pnl": 500.0,
                "reason": "TARGET",
            }
        ]

    def snapshot(self):
        return {
            "open_positions": 0,
            "positions": [],
            "unrealized_pnl": 0.0,
            "realized_pnl": 500.0,
            "total_pnl": 500.0,
        }

    def restore_open(self):
        return 0

    def close(self):
        pass


class Notifications:
    def __init__(self, fail=False):
        self.fail = fail
        self.opened = []
        self.closed = []
        self.kills = []

    def _maybe_fail(self):
        if self.fail:
            raise RuntimeError("notifications unavailable")

    def paper_opened(self, **kwargs):
        self._maybe_fail()
        self.opened.append(dict(kwargs))

    def paper_closed(self, row, **kwargs):
        self._maybe_fail()
        self.closed.append((dict(row), dict(kwargs)))

    def kill_switch_changed(self, **kwargs):
        self._maybe_fail()
        self.kills.append(dict(kwargs))


def order():
    return SimpleNamespace(
        symbol="TCS",
        side="BUY",
        quantity=5,
        price=3000.0,
        stoploss=2950.0,
        target2=3100.0,
    )


def test_paper_service_emits_open_close_and_changed_kill_switch():
    notifications = Notifications()
    service = PaperTradingService(
        Runtime(),
        enabled=True,
        environment_kill_switch=False,
        notifications=notifications,
    )

    opened = service.open(order())
    monitored = service.monitor({"tcs": 3100})
    service.set_runtime_kill_switch(True)
    service.set_runtime_kill_switch(True)
    service.set_runtime_kill_switch(False)

    assert opened["trade_id"] == 41
    assert monitored["closed"][0]["trade_id"] == 41
    assert notifications.opened[0]["symbol"] == "TCS"
    assert notifications.opened[0]["trade_id"] == 41
    assert notifications.closed[0][0]["reason"] == "TARGET"
    assert notifications.kills == [
        {"enabled": True},
        {"enabled": False},
    ]


def test_notification_failure_never_changes_paper_outcome():
    runtime = Runtime()
    service = PaperTradingService(
        runtime,
        enabled=True,
        environment_kill_switch=False,
        notifications=Notifications(fail=True),
    )

    opened = service.open(order())
    monitored = service.monitor({"TCS": 3100})
    health = service.set_runtime_kill_switch(True)

    assert opened["status"] == "opened"
    assert opened["trade_id"] == 41
    assert monitored["status"] == "monitored"
    assert monitored["closed"][0]["reason"] == "TARGET"
    assert health["runtime_kill_switch"] is True
    assert len(runtime.open_calls) == 1
    assert len(runtime.monitor_calls) == 1
