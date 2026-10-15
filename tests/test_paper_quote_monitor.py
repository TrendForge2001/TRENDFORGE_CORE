from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from services.paper_quote_monitor import PaperQuoteMonitor


class FakePaper:
    def __init__(self, positions=None):
        self.runtime = SimpleNamespace(
            portfolio=SimpleNamespace(
                positions=dict(positions or {})
            )
        )
        self.monitor_calls = []

    def monitor(self, quotes, now=None):
        self.monitor_calls.append((dict(quotes), now))
        closed = []
        for symbol in list(
            self.runtime.portfolio.positions
        ):
            if symbol in quotes:
                closed.append(
                    {
                        "symbol": symbol,
                        "exit_price": quotes[symbol],
                        "reason": "TARGET",
                    }
                )
                self.runtime.portfolio.positions.pop(
                    symbol,
                    None,
                )
        return {
            "closed": closed,
            "open_positions": len(
                self.runtime.portfolio.positions
            ),
            "total_pnl": 125.0,
        }


class FakeKite:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error
        self.validate_calls = 0
        self.ltp_calls = []

    def validate_live_session(self):
        self.validate_calls += 1
        if self.error:
            raise self.error

    def safe_ltp(self, instruments):
        self.ltp_calls.append(list(instruments))
        if self.error:
            raise self.error
        return self.payload


def test_tick_is_idle_without_open_positions():
    paper = FakePaper()
    kite = FakeKite()
    monitor = PaperQuoteMonitor(
        paper,
        kite,
        enabled=True,
        poll_interval_seconds=5,
        idle_interval_seconds=5,
    )

    result = monitor.tick(
        now=datetime(2026, 10, 16, 10, 0)
    )

    assert result["status"] == "idle"
    assert kite.validate_calls == 0
    assert kite.ltp_calls == []
    assert paper.monitor_calls == []


def test_tick_reads_kite_ltp_and_delegates_paper_exit():
    paper = FakePaper({"TCS": object()})
    kite = FakeKite(
        {
            "NSE:TCS": {
                "last_price": 3150.25,
            }
        }
    )
    monitor = PaperQuoteMonitor(
        paper,
        kite,
        enabled=True,
        poll_interval_seconds=5,
        idle_interval_seconds=5,
    )

    result = monitor.tick(
        now=datetime(2026, 10, 16, 10, 0)
    )

    assert kite.validate_calls == 1
    assert kite.ltp_calls == [["NSE:TCS"]]
    assert paper.monitor_calls[0][0] == {
        "TCS": 3150.25
    }
    assert result["status"] == "monitored"
    assert result["closed"][0]["symbol"] == "TCS"
    assert monitor.quote_success_count == 1
    assert monitor.closed_count == 1
    assert monitor.health()["broker_orders_allowed"] is False


def test_tick_fails_closed_when_any_open_symbol_has_no_quote():
    paper = FakePaper(
        {
            "TCS": object(),
            "INFY": object(),
        }
    )
    kite = FakeKite(
        {
            "NSE:TCS": {
                "last_price": 3100.0,
            }
        }
    )
    monitor = PaperQuoteMonitor(
        paper,
        kite,
        enabled=True,
    )

    with pytest.raises(
        RuntimeError,
        match="INFY",
    ):
        monitor.tick(
            now=datetime(2026, 10, 16, 10, 0)
        )

    assert paper.monitor_calls == []
    assert monitor.quote_failure_count == 1
    assert monitor.last_error


def test_quote_auth_failure_is_observable():
    paper = FakePaper({"TCS": object()})
    kite = FakeKite(error=RuntimeError("expired token"))
    monitor = PaperQuoteMonitor(
        paper,
        kite,
        enabled=True,
    )

    with pytest.raises(
        RuntimeError,
        match="expired token",
    ):
        monitor.tick(
            now=datetime(2026, 10, 16, 10, 0)
        )

    health = monitor.health()
    assert health["quote_failure_count"] == 1
    assert "expired token" in health["last_error"]


def test_background_monitor_can_start_and_stop():
    paper = FakePaper()
    kite = FakeKite()
    monitor = PaperQuoteMonitor(
        paper,
        kite,
        enabled=True,
        poll_interval_seconds=5,
        idle_interval_seconds=5,
    )

    async def scenario():
        assert await monitor.start() is True
        await asyncio.sleep(0)
        assert monitor.health()["running"] is True
        await monitor.stop()
        assert monitor.health()["running"] is False

    asyncio.run(scenario())


def test_disabled_monitor_does_not_start_task():
    monitor = PaperQuoteMonitor(
        FakePaper(),
        FakeKite(),
        enabled=False,
    )

    async def scenario():
        assert await monitor.start() is False
        assert monitor.health()["status"] == "disabled"
        assert monitor.health()["running"] is False
        await monitor.stop()

    asyncio.run(scenario())
