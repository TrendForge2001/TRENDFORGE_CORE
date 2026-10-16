from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_notification_policy_mutations_are_admin_protected():
    assert _protected_admin_request(
        "PUT",
        "/notifications/policy",
    )
    assert _protected_admin_request(
        "DELETE",
        "/notifications/policy",
    )


def test_daily_summary_send_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/notifications/daily-summary/send",
    )


def test_notification_policy_and_summary_reads_are_public_read_contracts():
    for path in (
        "/notifications/policy",
        "/notifications/daily-summary/readiness",
        "/notifications/daily-summary/preview",
    ):
        assert not _protected_admin_request(
            "GET",
            path,
        )
