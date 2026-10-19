from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.operations_reliability_service import (
    OperationsReliabilityService,
)


IST = ZoneInfo("Asia/Kolkata")


class Repo:
    MAX_AUDIT_EVENTS = 300

    def __init__(self):
        self.rows = []

    def record_audit_event(self, event):
        self.rows.append(dict(event))
        return dict(event)

    def audit_events(self, *, limit=100, operation=None):
        rows = list(self.rows)
        if operation:
            rows = [
                row
                for row in rows
                if row.get("operation") == operation
            ]
        return rows[-limit:][::-1]

    def audit_event(self, event_key):
        for row in reversed(self.rows):
            if row.get("event_key") == event_key:
                return dict(row)
        return None


class Operations:
    def __init__(self):
        self.contracts = {}

    def external_contract(self, operation, *, now=None):
        configured = self.contracts.get(operation)
        if configured:
            return dict(configured)
        current = now or datetime(
            2026, 10, 16, 9, 25, tzinfo=IST
        )
        return {
            "status": "satisfied",
            "reason": "successful_run_recorded",
            "operation": operation,
            "date_ist": current.date().isoformat(),
            "now_ist": current.isoformat(),
            "market_day": True,
            "market_phase": "market_open_paper_entry",
            "window_start_ist": current.replace(
                hour=8 if operation == "morning" else 15,
                minute=45,
            ).isoformat(),
            "window_end_ist": current.replace(
                hour=9 if operation == "morning" else 16,
                minute=15,
            ).isoformat(),
            "successful_run": {
                "run_id": f"{operation}-1",
                "status": "completed",
                "completed_at_ist": current.replace(
                    hour=8 if operation == "morning" else 15,
                    minute=50,
                ).isoformat(),
            },
            "automation_enabled": True,
            "operation_enabled": True,
            "broker_orders_allowed": False,
        }


class Center:
    def __init__(self, status="sent"):
        self.status = status
        self.calls = []

    def route_event(self, **kwargs):
        self.calls.append(dict(kwargs))
        return {
            "status": self.status,
            "event_id": f"evt-{len(self.calls)}",
        }


def at(hour, minute):
    return datetime(
        2026,
        10,
        16,
        hour,
        minute,
        tzinfo=IST,
    )


def build():
    repo = Repo()
    ops = Operations()
    center = Center()
    service = OperationsReliabilityService(
        operations_service=ops,
        repository=repo,
        notification_center=center,
    )
    return service, repo, ops, center


def test_healthy_post_window_audit_records_completion_delay():
    service, repo, _, center = build()

    result = service.audit(
        "morning",
        now=at(9, 25),
        strict=True,
        trigger_source="external_post_window",
    )

    assert result["status"] == "healthy"
    assert result["broker_orders_allowed"] is False
    assert result["audit"]["completion_delay_minutes"] == 5.0
    assert result["alert"] is None
    assert len(repo.rows) == 1
    assert center.calls == []


def test_missed_run_sends_critical_discord_alert():
    service, repo, ops, center = build()
    ops.contracts["morning"] = {
        "status": "missed_window",
        "reason": "window_elapsed_without_success",
        "operation": "morning",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T08:45:00+05:30",
        "window_end_ist": "2026-10-16T09:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }

    result = service.audit(
        "morning",
        now=at(9, 25),
        strict=True,
        trigger_source="external_post_window",
    )

    assert result["status"] == "missed"
    assert center.calls[0]["severity"] == "CRITICAL"
    assert center.calls[0]["category"] == "system"
    assert (
        center.calls[0]["dedupe_key"]
        == "operations-reliability:2026-10-16:morning:missed"
    )
    assert result["audit"]["alert"]["status"] == "sent"
    assert repo.rows[-1]["audit_status"] == "missed"


def test_strict_audit_flags_automation_drift():
    service, _, ops, center = build()
    ops.contracts["eod"] = {
        "status": "not_required",
        "reason": "automation_disabled",
        "operation": "eod",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "post_market",
        "window_start_ist": "2026-10-16T15:45:00+05:30",
        "window_end_ist": "2026-10-16T16:15:00+05:30",
        "successful_run": None,
        "automation_enabled": False,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }

    result = service.audit(
        "eod",
        now=at(16, 25),
        strict=True,
        trigger_source="external_post_window",
    )

    assert result["status"] == "configuration_error"
    assert center.calls[0]["severity"] == "ERROR"
    assert "Automation Drift" in center.calls[0]["title"]


def test_non_market_day_is_not_required_without_alert():
    service, _, ops, center = build()
    ops.contracts["morning"] = {
        "status": "not_required",
        "reason": "non_market_day",
        "operation": "morning",
        "date_ist": "2026-10-18",
        "market_day": False,
        "market_phase": "closed_non_market_day",
        "window_start_ist": "2026-10-18T08:45:00+05:30",
        "window_end_ist": "2026-10-18T09:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }

    result = service.audit(
        "morning",
        now=datetime(
            2026, 10, 18, 9, 25, tzinfo=IST
        ),
        strict=True,
    )

    assert result["status"] == "not_required"
    assert center.calls == []


def test_daily_alert_dedupe_skips_second_successfully_delivered_alert():
    service, _, ops, center = build()
    contract = {
        "status": "missed_window",
        "reason": "window_elapsed_without_success",
        "operation": "morning",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T08:45:00+05:30",
        "window_end_ist": "2026-10-16T09:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }
    ops.contracts["morning"] = contract

    first = service.audit(
        "morning",
        now=at(9, 25),
        strict=True,
    )
    second = service.audit(
        "morning",
        now=at(9, 30),
        strict=True,
    )

    assert first["alert"]["status"] == "sent"
    assert second["alert"]["status"] == "already_alerted"
    assert len(center.calls) == 1


def test_failed_alert_can_retry_on_later_audit():
    repo = Repo()
    ops = Operations()
    ops.contracts["morning"] = {
        "status": "missed_window",
        "reason": "window_elapsed_without_success",
        "operation": "morning",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T08:45:00+05:30",
        "window_end_ist": "2026-10-16T09:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }
    center = Center(status="blocked")
    service = OperationsReliabilityService(
        operations_service=ops,
        repository=repo,
        notification_center=center,
    )

    service.audit("morning", now=at(9, 25), strict=True)
    center.status = "sent"
    result = service.audit(
        "morning",
        now=at(9, 30),
        strict=True,
    )

    assert len(center.calls) == 2
    assert result["alert"]["status"] == "sent"


def test_external_tick_is_recorded_separately_from_post_window_audit():
    service, repo, _, _ = build()

    row = service.record_external_tick(
        operation="morning",
        before={"status": "due"},
        tick={"status": "active_window"},
        after={
            "status": "satisfied",
            "reason": "successful_run_recorded",
            "date_ist": "2026-10-16",
            "window_start_ist": "2026-10-16T08:45:00+05:30",
            "successful_run": {
                "completed_at_ist": "2026-10-16T08:50:00+05:30",
            },
        },
        now=at(8, 50),
    )

    assert row["event_type"] == "external_tick"
    assert row["audit_status"] == "healthy"
    assert row["completion_delay_minutes"] == 5.0
    assert len(repo.rows) == 1


def test_reliability_metrics_use_post_window_audits_not_duplicate_ticks():
    service, repo, _, _ = build()
    repo.rows = [
        {
            "event_type": "external_tick",
            "recorded_at_ist": "2026-10-16T08:50:00+05:30",
            "operation": "morning",
            "audit_status": "healthy",
        },
        {
            "event_type": "post_window_audit",
            "recorded_at_ist": "2026-10-16T09:25:00+05:30",
            "operation": "morning",
            "audit_status": "healthy",
            "completion_delay_minutes": 5.0,
        },
        {
            "event_type": "post_window_audit",
            "recorded_at_ist": "2026-10-16T16:25:00+05:30",
            "operation": "eod",
            "audit_status": "missed",
            "completion_delay_minutes": None,
        },
    ]

    result = service.reliability(
        days=30,
        now=datetime(
            2026, 10, 17, 8, 0, tzinfo=IST
        ),
    )

    assert result["health"] == "RED"
    assert result["measured_operations"] == 2
    assert result["healthy_operations"] == 1
    assert result["failed_operations"] == 1
    assert result["reliability_pct"] == 50.0
    assert (
        result["per_operation"]["morning"]["external_ticks"]
        == 1
    )
    assert (
        result["per_operation"]["morning"]["reliability_pct"]
        == 100.0
    )
    assert (
        result["per_operation"]["eod"]["reliability_pct"]
        == 0.0
    )


def test_reliability_turns_red_when_post_window_verification_is_missing():
    service, repo, ops, _ = build()
    current = datetime(
        2026,
        10,
        16,
        9,
        30,
        tzinfo=IST,
    )
    ops.contracts["morning"] = {
        "status": "satisfied",
        "reason": "successful_run_recorded",
        "operation": "morning",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T08:45:00+05:30",
        "window_end_ist": "2026-10-16T09:15:00+05:30",
        "successful_run": {
            "run_id": "morning-1",
            "status": "completed",
            "completed_at_ist": "2026-10-16T08:50:00+05:30",
        },
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }
    ops.contracts["eod"] = {
        "status": "pending",
        "reason": "before_window",
        "operation": "eod",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T15:45:00+05:30",
        "window_end_ist": "2026-10-16T16:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }

    result = service.reliability(
        days=7,
        now=current,
    )

    assert result["health"] == "RED"
    assert result["verification_gaps"] == ["morning"]


def test_reliability_live_missed_contract_is_red_without_audit_row():
    service, _, ops, _ = build()
    ops.contracts["morning"] = {
        "status": "missed_window",
        "reason": "window_elapsed_without_success",
        "operation": "morning",
        "date_ist": "2026-10-16",
        "market_day": True,
        "market_phase": "market_open_paper_entry",
        "window_start_ist": "2026-10-16T08:45:00+05:30",
        "window_end_ist": "2026-10-16T09:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }

    result = service.reliability(
        days=7,
        now=at(9, 30),
    )

    assert result["health"] == "RED"
    assert (
        result["current_contracts"]["morning"]["status"]
        == "missed_window"
    )


def test_reliability_counts_one_post_window_audit_per_operation_date():
    service, repo, ops, _ = build()
    ops.contracts["morning"] = {
        "status": "satisfied",
        "reason": "successful_run_recorded",
        "operation": "morning",
        "date_ist": "2026-10-17",
        "market_day": True,
        "market_phase": "post_market",
        "window_start_ist": "2026-10-17T08:45:00+05:30",
        "window_end_ist": "2026-10-17T09:15:00+05:30",
        "successful_run": {
            "run_id": "m",
            "status": "completed",
            "completed_at_ist": "2026-10-17T08:50:00+05:30",
        },
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }
    ops.contracts["eod"] = {
        "status": "pending",
        "reason": "before_window",
        "operation": "eod",
        "date_ist": "2026-10-17",
        "market_day": True,
        "market_phase": "pre_market",
        "window_start_ist": "2026-10-17T15:45:00+05:30",
        "window_end_ist": "2026-10-17T16:15:00+05:30",
        "successful_run": None,
        "automation_enabled": True,
        "operation_enabled": True,
        "broker_orders_allowed": False,
    }
    repo.rows = [
        {
            "event_type": "post_window_audit",
            "recorded_at_ist": "2026-10-16T09:25:00+05:30",
            "date_ist": "2026-10-16",
            "operation": "morning",
            "audit_status": "healthy",
            "completion_delay_minutes": 5.0,
        },
        {
            "event_type": "post_window_audit",
            "recorded_at_ist": "2026-10-16T09:35:00+05:30",
            "date_ist": "2026-10-16",
            "operation": "morning",
            "audit_status": "healthy",
            "completion_delay_minutes": 5.0,
        },
    ]

    result = service.reliability(
        days=7,
        now=datetime(
            2026, 10, 17, 8, 0, tzinfo=IST
        ),
    )

    morning = result["per_operation"]["morning"]
    assert morning["audit_checks"] == 1
    assert morning["healthy"] == 1
    assert morning["reliability_pct"] == 100.0
