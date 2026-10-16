from __future__ import annotations

from api.production_runtime import _protected_admin_request


def test_backtest_run_is_admin_protected():
    assert _protected_admin_request(
        "POST",
        "/backtests",
    )


def test_backtest_reads_remain_read_only():
    assert not _protected_admin_request(
        "GET",
        "/backtests/readiness",
    )
    assert not _protected_admin_request(
        "GET",
        "/backtests",
    )
    assert not _protected_admin_request(
        "GET",
        "/backtests/bt-123",
    )
