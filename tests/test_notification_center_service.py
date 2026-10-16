from __future__ import annotations

from services.notification_center_service import (
    NotificationCenterService,
    NotificationEventNotFoundError,
)


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def create(self, event):
        row = {
            **event,
            "created_at": event.get(
                "created_at",
                "2026-10-16T10:00:00+00:00",
            ),
            "updated_at": "2026-10-16T10:00:00+00:00",
            "sent_at": event.get("sent_at"),
        }
        self.rows[row["event_id"]] = row
        return dict(row)

    def get(self, event_id):
        row = self.rows.get(event_id)
        return dict(row) if row else None

    def update_delivery(
        self,
        event_id,
        *,
        status,
        error=None,
        sent_at=None,
    ):
        row = self.rows[event_id]
        row["status"] = status
        row["error"] = error
        row["sent_at"] = sent_at
        return dict(row)

    def latest(
        self,
        *,
        limit=100,
        category=None,
        status=None,
        symbol=None,
    ):
        rows = list(self.rows.values())
        if category:
            rows = [
                row for row in rows
                if row.get("category") == category
            ]
        if status:
            rows = [
                row for row in rows
                if row.get("status") == status
            ]
        if symbol:
            rows = [
                row for row in rows
                if row.get("symbol") == symbol
            ]
        return [dict(row) for row in rows[-limit:]][::-1]

    def recent_dedupe(self, dedupe_key, *, since):
        for row in reversed(list(self.rows.values())):
            if (
                row.get("dedupe_key") == dedupe_key
                and row.get("status") in {"sent", "recorded"}
            ):
                return dict(row)
        return None

    def count(self, *, status=None):
        if status is None:
            return len(self.rows)
        return sum(
            1
            for row in self.rows.values()
            if row.get("status") == status
        )

    def category_counts(self):
        result = {}
        for row in self.rows.values():
            category = row["category"]
            result[category] = result.get(category, 0) + 1
        return result

    def close(self):
        pass


class FakePolicy:
    def current(self):
        return {
            "status": "default",
            "source": "test",
            "updated_at": None,
            "policy": {
                "version": "R68.9",
                "delivery_enabled": True,
            },
        }

    def evaluate(self, **kwargs):
        return {
            "allowed": True,
            "reason": None,
            "policy": {
                "version": "R68.9",
            },
        }

    def close(self):
        pass


class FakeDiscord:
    def __init__(self, *, configured=True, ok=True):
        self.configured = configured
        self.ok = ok
        self.calls = []

    def enabled(self):
        return self.configured

    def health(self):
        return {
            "status": (
                "ready" if self.configured else "not_configured"
            ),
            "enabled": self.configured,
            "configured": self.configured,
            "provider": "Discord",
            "webhook_secret_exposed": False,
        }

    def send_notification(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.ok:
            return {
                "ok": True,
                "status": "sent",
                "provider": "Discord",
                "http_status": 204,
            }
        return {
            "ok": False,
            "status": "failed",
            "provider": "Discord",
            "error": "network failed",
        }


def build_service(*, configured=True, ok=True, cooldown=15):
    return NotificationCenterService(
        discord=FakeDiscord(
            configured=configured,
            ok=ok,
        ),
        repository=FakeRepository(),
        cooldown_minutes=cooldown,
        policy=FakePolicy(),
    )


def test_route_event_delivers_and_persists_sent_status():
    service = build_service()

    event = service.route_event(
        event_type="scanner_pick",
        category="scanner",
        severity="SUCCESS",
        title="TCS Scanner Alert",
        message="TCS qualifies",
        symbol="tcs",
        payload={"score": 94},
    )

    assert event["status"] == "sent"
    assert event["symbol"] == "TCS"
    assert event["payload"]["score"] == 94
    assert event["sent_at"]
    assert len(service.discord.calls) == 1


def test_duplicate_event_is_suppressed_within_cooldown():
    service = build_service()

    first = service.route_event(
        event_type="risk_block",
        category="risk",
        severity="WARNING",
        title="Risk",
        message="Daily loss limit",
        dedupe_key="risk:daily-loss",
    )
    second = service.route_event(
        event_type="risk_block",
        category="risk",
        severity="WARNING",
        title="Risk",
        message="Daily loss limit",
        dedupe_key="risk:daily-loss",
    )

    assert first["status"] == "sent"
    assert second["status"] == "suppressed"
    assert second["payload"]["duplicate_of"] == first["event_id"]
    assert len(service.discord.calls) == 1


def test_missing_discord_blocks_without_network_attempt():
    service = build_service(configured=False)

    event = service.route_event(
        event_type="system",
        category="system",
        title="System",
        message="No webhook",
    )

    assert event["status"] == "blocked"
    assert event["error"] == "discord_not_configured"
    assert service.discord.calls == []


def test_record_only_event_does_not_deliver():
    service = build_service()

    event = service.route_event(
        event_type="research_note",
        category="intelligence",
        title="Evidence",
        message="Record only",
        deliver=False,
    )

    assert event["status"] == "recorded"
    assert service.discord.calls == []


def test_delivery_failure_is_persisted():
    service = build_service(ok=False)

    event = service.route_event(
        event_type="system_error",
        category="system",
        severity="ERROR",
        title="System Error",
        message="Provider failed",
    )

    assert event["status"] == "failed"
    assert event["error"] == "network failed"


def test_summary_and_filters():
    service = build_service()
    service.route_event(
        event_type="one",
        category="scanner",
        title="One",
        message="one",
        deliver=False,
    )
    service.route_event(
        event_type="two",
        category="risk",
        title="Two",
        message="two",
        deliver=False,
    )

    summary = service.summary()
    filtered = service.events(category="risk")

    assert summary["total"] == 2
    assert summary["recorded"] == 2
    assert summary["categories"] == {
        "scanner": 1,
        "risk": 1,
    }
    assert filtered["returned"] == 1
    assert filtered["events"][0]["category"] == "risk"


def test_readiness_is_discord_only():
    readiness = build_service().readiness()

    assert readiness["channel"] == "discord"
    assert readiness["whatsapp_supported"] is False
    assert readiness["email_supported"] is False
    assert readiness["webhook_secret_exposed"] is False


def test_get_missing_event_raises_not_found():
    service = build_service()

    try:
        service.get("missing")
    except NotificationEventNotFoundError:
        pass
    else:
        raise AssertionError("expected NotificationEventNotFoundError")


class TogglePolicy(FakePolicy):
    def __init__(self, allowed=True, reason="category_disabled"):
        self.allowed = allowed
        self.reason = reason

    def evaluate(self, **kwargs):
        return {
            "allowed": self.allowed,
            "reason": None if self.allowed else self.reason,
            "policy": {
                "version": "R68.9",
            },
        }


def test_policy_filtered_event_is_persisted_without_discord_call():
    policy = TogglePolicy(allowed=False)
    service = NotificationCenterService(
        discord=FakeDiscord(),
        repository=FakeRepository(),
        cooldown_minutes=15,
        policy=policy,
    )

    event = service.route_event(
        event_type="scanner_pick",
        category="scanner",
        severity="SUCCESS",
        title="TCS",
        message="Pick",
        dedupe_key="same-key",
    )

    assert event["status"] == "filtered"
    assert event["error"] == "policy:category_disabled"
    assert event["payload"]["policy_filtered"] is True
    assert service.discord.calls == []
    assert service.summary()["filtered"] == 1


def test_policy_is_evaluated_before_cooldown_dedupe():
    policy = TogglePolicy(allowed=True)
    service = NotificationCenterService(
        discord=FakeDiscord(),
        repository=FakeRepository(),
        cooldown_minutes=15,
        policy=policy,
    )

    first = service.route_event(
        event_type="scanner_pick",
        category="scanner",
        severity="SUCCESS",
        title="TCS",
        message="Pick",
        dedupe_key="same-key",
    )
    policy.allowed = False
    second = service.route_event(
        event_type="scanner_pick",
        category="scanner",
        severity="SUCCESS",
        title="TCS",
        message="Pick",
        dedupe_key="same-key",
    )

    assert first["status"] == "sent"
    assert second["status"] == "filtered"
    assert len(service.discord.calls) == 1


def test_policy_bypass_is_reserved_for_internal_delivery():
    policy = TogglePolicy(allowed=False)
    service = NotificationCenterService(
        discord=FakeDiscord(),
        repository=FakeRepository(),
        cooldown_minutes=0,
        policy=policy,
    )

    event = service.route_event(
        event_type="internal_summary",
        category="system",
        severity="INFO",
        title="Summary",
        message="Internal",
        policy_bypass=True,
    )

    assert event["status"] == "sent"
    assert len(service.discord.calls) == 1
