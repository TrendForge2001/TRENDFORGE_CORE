from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_operations_mutations_are_admin_protected():
    assert _protected_admin_request(
        "PUT",
        "/operations/policy",
    )
    assert _protected_admin_request(
        "DELETE",
        "/operations/policy",
    )
    assert _protected_admin_request(
        "POST",
        "/operations/tick",
    )
    assert _protected_admin_request(
        "POST",
        "/operations/run/morning",
    )
    assert _protected_admin_request(
        "POST",
        "/operations/run/eod",
    )


def test_operations_reads_are_not_admin_mutations():
    for path in (
        "/operations/readiness",
        "/operations/session",
        "/operations/policy",
        "/operations/control-center",
        "/operations/runs",
    ):
        assert not _protected_admin_request(
            "GET",
            path,
        )
