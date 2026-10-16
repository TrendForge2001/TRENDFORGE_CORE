from __future__ import annotations

from services.notification_daily_summary_service import (
    NotificationDailySummaryService,
)


class Repo:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.sent = {}

    def between(self, *, start, end, limit=2000):
        return list(self.rows)[:limit]

    def find_dedupe(self, dedupe_key, *, statuses=("sent", "recorded")):
        row = self.sent.get(dedupe_key)
        return dict(row) if row else None


class Center:
    def __init__(self, rows=None):
        self.repository = Repo(rows)
        self.calls = []

    def route_event(self, **kwargs):
        self.calls.append(dict(kwargs))
        row = {
            "event_id": f"evt-{len(self.calls)}",
            "status": "sent",
            **kwargs,
        }
        self.repository.sent[kwargs["dedupe_key"]] = row
        return row


class Policy:
    def __init__(
        self,
        *,
        enabled=True,
        skip_empty=True,
        notable_limit=10,
        delivery_enabled=True,
    ):
        self.enabled = enabled
        self.skip_empty = skip_empty
        self.notable_limit = notable_limit
        self.delivery_enabled = delivery_enabled

    def current(self):
        return {
            "policy": {
                "delivery_enabled": self.delivery_enabled,
                "daily_summary": {
                    "enabled": self.enabled,
                    "time_ist": "18:30",
                    "skip_empty": self.skip_empty,
                    "notable_limit": self.notable_limit,
                }
            }
        }


def row(
    event_id,
    *,
    event_type,
    category,
    severity="INFO",
    status="sent",
    symbol=None,
    title=None,
):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "category": category,
        "severity": severity,
        "status": status,
        "symbol": symbol,
        "title": title or event_type,
        "message": event_type,
        "created_at": "2026-10-16T10:00:00+00:00",
    }


def test_preview_aggregates_canonical_notification_evidence():
    center = Center(
        [
            row(
                "1",
                event_type="scanner_pick",
                category="scanner",
                severity="SUCCESS",
                symbol="TCS",
            ),
            row(
                "2",
                event_type="paper_position_opened",
                category="paper",
                severity="SUCCESS",
                symbol="INFY",
            ),
            row(
                "3",
                event_type="paper_position_closed",
                category="paper",
                severity="WARNING",
                symbol="INFY",
            ),
            row(
                "4",
                event_type="paper_risk_block",
                category="risk",
                severity="CRITICAL",
                status="failed",
            ),
            row(
                "5",
                event_type="daily_discord_summary",
                category="system",
            ),
        ]
    )
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(),
    )

    preview = service.preview(
        summary_date="2026-10-16"
    )

    assert preview["event_count"] == 4
    assert preview["scanner_picks"] == 1
    assert preview["paper_opened"] == 1
    assert preview["paper_closed"] == 1
    assert preview["risk_events"] == 1
    assert preview["delivery_issues"] == 1
    assert preview["statuses"]["failed"] == 1
    assert preview["window"]["start_utc"].startswith(
        "2026-10-15T18:30:00"
    )


def test_send_is_disabled_by_policy():
    center = Center([row("1", event_type="scanner_pick", category="scanner")])
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(enabled=False),
    )

    result = service.send(
        summary_date="2026-10-16"
    )

    assert result["status"] == "disabled"
    assert center.calls == []


def test_send_skips_empty_day_when_configured():
    center = Center()
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(
            enabled=True,
            skip_empty=True,
        ),
    )

    result = service.send(
        summary_date="2026-10-16"
    )

    assert result["status"] == "skipped_empty"
    assert center.calls == []


def test_send_delivers_once_per_day_and_bypasses_category_policy():
    center = Center(
        [
            row(
                "1",
                event_type="scanner_pick",
                category="scanner",
                severity="SUCCESS",
                symbol="TCS",
            )
        ]
    )
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(enabled=True),
    )

    first = service.send(
        summary_date="2026-10-16"
    )
    second = service.send(
        summary_date="2026-10-16"
    )

    assert first["status"] == "sent"
    assert second["status"] == "already_sent"
    assert len(center.calls) == 1
    call = center.calls[0]
    assert call["event_type"] == "daily_discord_summary"
    assert call["category"] == "system"
    assert call["policy_bypass"] is True
    assert call["dedupe_key"] == "daily-summary:2026-10-16"


def test_force_send_uses_unique_dedupe_key():
    center = Center(
        [row("1", event_type="scanner_pick", category="scanner")]
    )
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(enabled=True),
    )

    service.send(summary_date="2026-10-16")
    forced = service.send(
        summary_date="2026-10-16",
        force=True,
    )

    assert forced["status"] == "sent"
    assert len(center.calls) == 2
    assert center.calls[1]["dedupe_key"].startswith(
        "daily-summary:2026-10-16:force:"
    )


def test_send_respects_global_delivery_switch():
    center = Center(
        [row("1", event_type="scanner_pick", category="scanner")]
    )
    service = NotificationDailySummaryService(
        center=center,
        policy=Policy(
            enabled=True,
            delivery_enabled=False,
        ),
    )

    result = service.send(
        summary_date="2026-10-16"
    )

    assert result["status"] == "delivery_disabled"
    assert center.calls == []
