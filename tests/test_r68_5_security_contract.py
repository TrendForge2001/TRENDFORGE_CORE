from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_intelligence_refresh_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/intelligence/refresh",
    )


def test_intelligence_reads_are_not_admin_mutations():
    for path in (
        "/intelligence/readiness",
        "/intelligence/events",
        "/intelligence/TCS/summary",
        "/intelligence/TCS/news",
        "/intelligence/TCS/corporate-actions",
    ):
        assert not _protected_admin_request(
            "GET",
            path,
        )
