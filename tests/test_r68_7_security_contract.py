from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_notification_mutations_are_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/notifications/events",
    )
    assert _protected_admin_request(
        "POST",
        "/notifications/test",
    )


def test_notification_reads_are_not_admin_mutations():
    for path in (
        "/notifications/readiness",
        "/notifications/summary",
        "/notifications/events",
        "/notifications/events/evt-1",
    ):
        assert not _protected_admin_request("GET", path)
