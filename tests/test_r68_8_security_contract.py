from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_notification_producer_health_is_read_only():
    assert not _protected_admin_request(
        "GET",
        "/notifications/producers",
    )


def test_notification_delivery_mutations_remain_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/notifications/events",
    )
    assert _protected_admin_request(
        "POST",
        "/notifications/test",
    )
