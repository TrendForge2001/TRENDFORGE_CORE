from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_watchlist_mutations_are_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/watchlists/Swing/symbols",
    )
    assert _protected_admin_request(
        "PUT",
        "/watchlists/Swing/symbols/TCS",
    )
    assert _protected_admin_request(
        "DELETE",
        "/watchlists/Swing/symbols/TCS",
    )
    assert _protected_admin_request(
        "DELETE",
        "/watchlists/Swing",
    )


def test_market_context_refresh_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/market/context/refresh",
    )


def test_market_and_watchlist_reads_remain_read_only():
    assert not _protected_admin_request(
        "GET",
        "/watchlists",
    )
    assert not _protected_admin_request(
        "GET",
        "/watchlists/Swing",
    )
    assert not _protected_admin_request(
        "GET",
        "/market/breadth",
    )
    assert not _protected_admin_request(
        "GET",
        "/market/regime",
    )
