from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_institutional_refresh_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/institutional/refresh",
    )


def test_sector_strength_refresh_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/sector-strength/refresh",
    )


def test_institutional_and_sector_reads_are_read_only():
    for path in (
        "/institutional/readiness",
        "/institutional",
        "/institutional/TCS",
        "/sector-strength",
    ):
        assert not _protected_admin_request("GET", path)
