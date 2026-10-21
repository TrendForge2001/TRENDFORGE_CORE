from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_portfolio_sync_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/portfolio/sync",
    )


def test_private_portfolio_reporting_requires_authentication():
    assert _protected_admin_request(
        "GET",
        "/portfolio",
    )
    assert _protected_admin_request(
        "GET",
        "/pnl",
    )
    assert _protected_admin_request(
        "GET",
        "/performance",
    )
