from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from services.notification_policy_service import (
    NotificationPolicyService,
)


class Repo:
    def __init__(self, value=None):
        self.value = value
        self.updated = None

    def get(self):
        if self.value is None:
            return None
        return {
            "policy": self.value,
            "updated_at": self.updated,
        }

    def set(self, policy):
        self.value = dict(policy)
        self.updated = "2026-10-16T12:00:00+00:00"
        return {
            "policy": self.value,
            "updated_at": self.updated,
        }

    def reset(self):
        existed = self.value is not None
        self.value = None
        self.updated = None
        return existed

    def close(self):
        pass


def test_default_policy_is_discord_delivery_on_digest_off():
    service = NotificationPolicyService(repository=Repo())

    result = service.current()

    assert result["status"] == "default"
    policy = result["policy"]
    assert policy["version"] == "R68.9"
    assert policy["delivery_enabled"] is True
    assert policy["daily_summary"]["enabled"] is False
    assert policy["daily_summary"]["time_ist"] == "18:30"
    assert policy["risk"]["enabled"] if "risk" in policy else True
    assert policy["categories"]["risk"]["minimum_severity"] == "WARNING"


def test_policy_update_normalizes_all_categories_and_clocks():
    repo = Repo()
    service = NotificationPolicyService(repository=repo)

    result = service.update(
        {
            "delivery_enabled": True,
            "categories": {
                "scanner": {
                    "enabled": False,
                    "minimum_severity": "success",
                },
            },
            "quiet_hours": {
                "enabled": True,
                "start": "22:30",
                "end": "07:15",
                "allow_critical": True,
            },
            "daily_summary": {
                "enabled": True,
                "time_ist": "18:45",
                "skip_empty": False,
                "notable_limit": 12,
            },
        }
    )

    policy = result["policy"]
    assert policy["categories"]["scanner"] == {
        "enabled": False,
        "minimum_severity": "SUCCESS",
    }
    assert policy["categories"]["paper"]["enabled"] is True
    assert policy["quiet_hours"]["timezone"] == "Asia/Kolkata"
    assert policy["daily_summary"]["time_ist"] == "18:45"
    assert policy["daily_summary"]["notable_limit"] == 12


def test_category_and_minimum_severity_filtering():
    repo = Repo()
    service = NotificationPolicyService(repository=repo)
    policy = service.current()["policy"]
    policy["categories"]["scanner"]["enabled"] = False
    policy["categories"]["risk"]["minimum_severity"] = "ERROR"
    service.update(policy)

    disabled = service.evaluate(
        category="scanner",
        severity="CRITICAL",
    )
    low = service.evaluate(
        category="risk",
        severity="WARNING",
    )
    allowed = service.evaluate(
        category="risk",
        severity="ERROR",
    )

    assert disabled["allowed"] is False
    assert disabled["reason"] == "category_disabled"
    assert low["allowed"] is False
    assert low["reason"] == "severity_below_minimum:ERROR"
    assert allowed["allowed"] is True


def test_quiet_hours_cross_midnight_and_allow_critical():
    repo = Repo()
    service = NotificationPolicyService(repository=repo)
    policy = service.current()["policy"]
    policy["quiet_hours"] = {
        "enabled": True,
        "start": "22:00",
        "end": "07:00",
        "allow_critical": True,
    }
    service.update(policy)
    ist = ZoneInfo("Asia/Kolkata")

    warning = service.evaluate(
        category="risk",
        severity="WARNING",
        now=datetime(2026, 10, 16, 23, 0, tzinfo=ist),
    )
    critical = service.evaluate(
        category="risk",
        severity="CRITICAL",
        now=datetime(2026, 10, 17, 1, 0, tzinfo=ist),
    )
    daytime = service.evaluate(
        category="risk",
        severity="WARNING",
        now=datetime(2026, 10, 17, 10, 0, tzinfo=ist),
    )

    assert warning["reason"] == "quiet_hours"
    assert critical["allowed"] is True
    assert daytime["allowed"] is True


def test_invalid_clock_is_rejected():
    service = NotificationPolicyService(repository=Repo())

    try:
        service.update(
            {
                "quiet_hours": {
                    "start": "29:90",
                }
            }
        )
    except ValueError as exc:
        assert "HH:MM" in str(exc)
    else:
        raise AssertionError("invalid clock must fail")


def test_reset_restores_built_in_defaults():
    repo = Repo()
    service = NotificationPolicyService(repository=repo)
    policy = service.current()["policy"]
    policy["delivery_enabled"] = False
    service.update(policy)

    reset = service.reset()

    assert reset["status"] == "reset"
    assert reset["removed"] is True
    assert reset["policy"]["delivery_enabled"] is True
