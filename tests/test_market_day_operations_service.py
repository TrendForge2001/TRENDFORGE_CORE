from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.market_day_operations_service import (
    MarketDayOperationsService,
)


IST = ZoneInfo("Asia/Kolkata")


class Repo:
    def __init__(self):
        self.policy_value = None
        self.rows = []

    def policy(self):
        if self.policy_value is None:
            return None
        return {
            "policy": self.policy_value,
            "updated_at": "2026-10-16T00:00:00+00:00",
        }

    def set_policy(self, policy):
        self.policy_value = dict(policy)
        return {
            "policy": self.policy_value,
            "updated_at": "2026-10-16T00:00:00+00:00",
        }

    def reset_policy(self):
        existed = self.policy_value is not None
        self.policy_value = None
        return existed

    def runs(self, *, limit=20):
        return list(self.rows[-limit:])[::-1]

    def record_run(self, run):
        self.rows.append(dict(run))
        return dict(run)

    def successful_run(self, operation, date_ist):
        for row in reversed(self.rows):
            if (
                row.get("operation") == operation
                and row.get("date_ist") == date_ist
                and row.get("status")
                in {"completed", "degraded"}
            ):
                return dict(row)
        return None

    def close(self):
        pass


class MarketContext:
    def __init__(self, fail=False):
        self.fail = fail
        self.refresh_calls = []

    def refresh(self, **kwargs):
        self.refresh_calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("market data unavailable")
        return {
            "status": "ready",
            "requested_symbols": kwargs["limit"],
            "analyzed_symbols": kwargs["limit"],
            "coverage_pct": 100.0,
            "breadth": {
                "direction": "BULLISH",
                "breadth_score": 72.0,
            },
            "regime": {
                "regime": "BULL",
                "score": 81.0,
            },
        }

    def snapshot(self, kind):
        if kind == "breadth":
            return {
                "status": "ready",
                "direction": "BULLISH",
            }
        return {
            "status": "ready",
            "regime": "BULL",
        }


class PaperMonitor:
    def __init__(self, *, running=False):
        self.calls = []
        self.running = running

    def tick(self, *, now=None):
        self.calls.append(now)
        return {
            "status": "monitored",
            "symbols": ["TCS"],
            "closed": [
                {
                    "symbol": "TCS",
                    "reason": "FORCE_EXIT_15_00_IST",
                }
            ],
            "open_positions": 0,
            "total_pnl": 125.0,
        }

    def health(self):
        return {
            "status": (
                "running"
                if self.running
                else "disabled"
            ),
            "running": self.running,
            "open_position_count": 0,
        }


class Portfolio:
    def __init__(self):
        self.sync_calls = 0

    def sync_portfolio(self):
        self.sync_calls += 1
        return {
            "status": "synced",
            "scope": "live_kite_portfolio",
            "count": 3,
            "holdings": [
                {"symbol": "TCS"},
                {"symbol": "INFY"},
            ],
            "positions": [
                {"symbol": "RELIANCE"},
            ],
            "portfolio_value": 500000.0,
            "investment": 450000.0,
            "total_pnl": 50000.0,
        }

    def portfolio(self):
        return {
            "status": "ready",
            "portfolio_value": 500000.0,
        }

    def pnl_statement(self, *, period):
        assert period == "daily"
        return {
            "status": "ready",
            "summary": {
                "trade_count": 2,
                "net_pnl": 125.0,
                "winning_trades": 1,
                "losing_trades": 1,
            },
        }


class Center:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def route_event(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.fail:
            raise RuntimeError("discord down")
        return {
            "status": "sent",
            "event_id": f"event-{len(self.calls)}",
        }

    def readiness(self):
        return {
            "status": "ready",
            "channel": "discord",
        }


def friday(hour=8, minute=45):
    return datetime(
        2026,
        10,
        16,
        hour,
        minute,
        tzinfo=IST,
    )


def saturday(hour=10, minute=0):
    return datetime(
        2026,
        10,
        17,
        hour,
        minute,
        tzinfo=IST,
    )


def build_service(*, market_fail=False, center_fail=False):
    return MarketDayOperationsService(
        repository=Repo(),
        market_context=MarketContext(fail=market_fail),
        paper_monitor=PaperMonitor(),
        portfolio=Portfolio(),
        notification_center=Center(fail=center_fail),
    )


def test_default_policy_is_safe_and_automation_off():
    service = build_service()

    policy = service.policy()["policy"]

    assert policy["version"] == "R69.0"
    assert policy["automation_enabled"] is False
    assert policy["market_day_only"] is True
    assert policy["morning"]["time_ist"] == "08:45"
    assert policy["eod"]["time_ist"] == "15:45"
    assert policy["eod"]["portfolio_sync"] is False


def test_scheduled_run_respects_global_automation_switch():
    service = build_service()

    result = service.run(
        "morning",
        now=friday(),
        scheduled=True,
    )

    assert result["status"] == "automation_disabled"
    assert service.market_context.refresh_calls == []


def test_manual_morning_run_and_same_day_dedupe():
    service = build_service()

    first = service.run(
        "morning",
        now=friday(),
    )
    second = service.run(
        "morning",
        now=friday(9, 0),
    )

    assert first["status"] == "completed"
    assert first["completed_steps"] == 1
    assert first["failed_steps"] == 0
    assert first["broker_orders_allowed"] is False
    assert len(service.market_context.refresh_calls) == 1
    assert service.market_context.refresh_calls[0]["limit"] == 100
    assert len(service.notification_center.calls) == 1
    assert second["status"] == "already_completed"


def test_non_market_day_is_skipped_unless_forced():
    service = build_service()

    skipped = service.run(
        "morning",
        now=saturday(),
    )
    forced = service.run(
        "morning",
        now=saturday(),
        force=True,
    )

    assert skipped["status"] == "skipped_non_market_day"
    assert forced["status"] == "completed"
    assert forced["forced"] is True


def test_eod_runs_paper_safety_context_and_daily_pnl():
    service = build_service()

    result = service.run(
        "eod",
        now=friday(15, 45),
    )

    assert result["status"] == "completed"
    assert {
        step["step"]
        for step in result["steps"]
    } == {
        "market_context_refresh",
        "paper_safety_tick",
        "daily_pnl_snapshot",
    }
    paper = next(
        step
        for step in result["steps"]
        if step["step"] == "paper_safety_tick"
    )
    assert paper["result"]["paper_only"] is True
    assert paper["result"]["closed_count"] == 1
    assert service.portfolio.sync_calls == 0


def test_optional_portfolio_sync_stores_bounded_summary():
    service = build_service()
    policy = service.policy()["policy"]
    policy["eod"]["portfolio_sync"] = True
    service.update_policy(policy)

    result = service.run(
        "eod",
        now=friday(15, 45),
    )

    sync = next(
        step
        for step in result["steps"]
        if step["step"] == "portfolio_sync"
    )
    assert sync["result"]["holding_count"] == 2
    assert sync["result"]["position_count"] == 1
    assert "holdings" not in sync["result"]
    assert "positions" not in sync["result"]


def test_step_failure_degrades_run_but_notification_failure_does_not():
    degraded = build_service(market_fail=True)
    degraded_result = degraded.run(
        "morning",
        now=friday(),
    )
    assert degraded_result["status"] == "degraded"
    assert degraded_result["failed_steps"] == 1

    notification_fail = build_service(center_fail=True)
    completed = notification_fail.run(
        "morning",
        now=friday(),
    )
    assert completed["status"] == "completed"
    assert completed["notification"]["status"] == "failed"
    assert "notification_side_channel" in (
        completed["notification"]["error"]
    )


def test_control_center_is_read_only_snapshot():
    service = build_service()

    result = service.control_center(
        now=friday(10, 0)
    )

    assert result["status"] == "ready"
    assert result["session"]["market_day"] is True
    assert result["market"]["regime"]["regime"] == "BULL"
    assert result["portfolio"]["portfolio_value"] == 500000.0
    assert result["daily_pnl"]["net_pnl"] == 125.0
    assert result["safety"]["broker_orders_allowed"] is False
    assert result["safety"]["automatic_scanner_execution"] is False


def test_policy_rejects_conflicting_calendar_override():
    service = build_service()

    try:
        service.update_policy(
            {
                "calendar": {
                    "holiday_dates": ["2026-10-17"],
                    "special_trading_dates": ["2026-10-17"],
                }
            }
        )
    except ValueError as exc:
        assert "both holiday and special trading day" in str(exc)
    else:
        raise AssertionError("calendar conflict must fail")


def test_eod_delegates_to_running_automatic_paper_monitor():
    service = build_service()
    service.paper_monitor.running = True

    result = service.run(
        "eod",
        now=friday(15, 45),
    )

    paper = next(
        step
        for step in result["steps"]
        if step["step"] == "paper_safety_tick"
    )
    assert paper["result"]["status"] == "automatic_monitor_active"
    assert paper["result"]["direct_tick"] is False
    assert service.paper_monitor.calls == []


def test_external_contract_reports_not_required_when_automation_off():
    service = build_service()

    result = service.external_contract(
        "morning",
        now=friday(8, 45),
    )

    assert result["status"] == "not_required"
    assert result["reason"] == "automation_disabled"
    assert result["broker_orders_allowed"] is False


def test_external_contract_tracks_pending_due_satisfied_and_missed():
    service = build_service()
    policy = service.policy()["policy"]
    policy["automation_enabled"] = True
    service.update_policy(policy)

    pending = service.external_contract(
        "morning",
        now=friday(8, 44),
    )
    due = service.external_contract(
        "morning",
        now=friday(8, 45),
    )

    assert pending["status"] == "pending"
    assert pending["reason"] == "before_window"
    assert due["status"] == "due"
    assert due["reason"] == "inside_window"

    service.run(
        "morning",
        now=friday(8, 45),
        scheduled=True,
    )
    satisfied = service.external_contract(
        "morning",
        now=friday(9, 16),
    )

    assert satisfied["status"] == "satisfied"
    assert satisfied["successful_run"]["status"] == "completed"

    other = build_service()
    other_policy = other.policy()["policy"]
    other_policy["automation_enabled"] = True
    other.update_policy(other_policy)
    missed = other.external_contract(
        "morning",
        now=friday(9, 16),
    )

    assert missed["status"] == "missed_window"
    assert (
        missed["reason"]
        == "window_elapsed_without_success"
    )
