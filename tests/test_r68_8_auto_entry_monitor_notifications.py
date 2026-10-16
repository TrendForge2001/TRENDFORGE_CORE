from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_quote_monitor import PaperQuoteMonitor


class AutoNotifications:
    def __init__(self, fail=False):
        self.fail = fail
        self.results = []

    def auto_entry_result(self, result):
        if self.fail:
            raise RuntimeError("notification failed")
        self.results.append(dict(result))


class BlockedPaper:
    can_open_new_positions = False

    def __init__(self):
        self.runtime = SimpleNamespace(
            portfolio=SimpleNamespace(positions={}),
            trades=None,
        )


def test_auto_entry_reports_blocked_result_to_notification_bridge():
    notifications = AutoNotifications()
    service = PaperAutoEntryService(
        BlockedPaper(),
        enabled=True,
        notifications=notifications,
    )

    result = service.process_scan(
        {
            "outcome": "completed",
            "execution_top_picks": [],
        },
        run_id="blocked-run",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "paper_trading_not_ready"
    assert notifications.results[0]["run_id"] == "blocked-run"


def test_auto_entry_result_survives_notification_exception():
    service = PaperAutoEntryService(
        BlockedPaper(),
        enabled=True,
        notifications=AutoNotifications(fail=True),
    )

    result = service.process_scan(
        {
            "outcome": "completed",
            "execution_top_picks": [],
        },
        run_id="blocked-run",
        execute_requested=True,
        now=datetime(2026, 10, 16, 10, 0),
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "paper_trading_not_ready"


class MonitorNotifications:
    def __init__(self, fail=False):
        self.fail = fail
        self.errors = []

    def monitor_failed(self, *, error):
        if self.fail:
            raise RuntimeError("notification failed")
        self.errors.append(error)


class Paper:
    def __init__(self):
        self.runtime = SimpleNamespace(
            portfolio=SimpleNamespace(
                positions={"TCS": object()}
            )
        )


class BrokenQuotes:
    def validate_live_session(self):
        raise RuntimeError("expired token")


def test_quote_monitor_reports_failure_to_notification_bridge():
    notifications = MonitorNotifications()
    monitor = PaperQuoteMonitor(
        Paper(),
        BrokenQuotes(),
        enabled=True,
        notifications=notifications,
    )

    with pytest.raises(RuntimeError, match="expired token"):
        monitor.tick(now=datetime(2026, 10, 16, 10, 0))

    assert len(notifications.errors) == 1
    assert "expired token" in notifications.errors[0]


def test_quote_monitor_preserves_original_error_if_notifier_fails():
    monitor = PaperQuoteMonitor(
        Paper(),
        BrokenQuotes(),
        enabled=True,
        notifications=MonitorNotifications(fail=True),
    )

    with pytest.raises(RuntimeError, match="expired token"):
        monitor.tick(now=datetime(2026, 10, 16, 10, 0))

    assert monitor.quote_failure_count == 1
    assert "expired token" in str(monitor.last_error)
