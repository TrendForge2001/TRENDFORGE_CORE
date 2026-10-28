"""Diagnose a live backend without exposing credentials or submitting orders."""

from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import requests

from scanner.strategy_registry import REGISTRY_VERSION
from scripts.check_paper_runtime import diagnose

NOW = datetime(2026, 10, 28, 10, 15, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def runtime(tmp_path):
    private = tmp_path / "private"
    private.mkdir()
    key = "diagnostic-local-secret-" * 3
    (private / "admin-key.txt").write_text(key, encoding="utf-8")
    data = {
        "/paper/automation": {
            "enabled": True,
            "phase": "watching_market",
            "universe": "NIFTY 500",
            "settings_saved": True,
            "worker_running": True,
            "busy": False,
            "last_checked_at": NOW.isoformat(),
            "last_error": None,
            "blockers": [],
            "paper_only": True,
            "broker_orders_allowed": False,
            "target_symbols": ["TCS"],
            "target_strategy_ids": ["tf_intraday_ema9_20_momentum"],
        },
        "/paper/readiness": {
            "can_open_new_positions": True,
            "kill_switch": False,
            "broker_orders_allowed": False,
            "entry_storage_policy": {
                "mode": "durable",
                "verified_persistent": True,
                "entry_allowed": True,
            },
            "automatic_monitor": {"enabled": True, "running": True},
        },
        "/paper/strategy-monitor/readiness": {"enabled": True},
        "/technical/multi-strategy/validation/status": {
            "status": "completed",
            "registry_version": REGISTRY_VERSION,
            "run_id": "full-validation",
            "request": {
                "universes": ["NIFTY 500"],
                "source": "all",
                "modes": ["intraday", "swing", "positional"],
                "limit": None,
            },
        },
        "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true": {
            "authenticated": True,
            "quote_status": "fresh",
            "history_status": "available",
            "indicator_status": "calculated",
            "broker_orders_allowed": False,
        },
    }
    calls = []

    class Session:
        trust_env = True

        def get(self, url, **kwargs):
            assert url.startswith("http://127.0.0.1:10000/")
            assert kwargs["headers"] == {"X-TrendForge-Admin-Key": key}
            assert kwargs["allow_redirects"] is False
            assert kwargs["timeout"] == 20
            calls.append(url)
            body = deepcopy(data[url.removeprefix("http://127.0.0.1:10000")])
            return SimpleNamespace(status_code=200, json=lambda: body)

    return SimpleNamespace(
        root=tmp_path, session=Session(), data=data, calls=calls, key=key
    )


def test_running_backend_is_checked_only_by_authenticated_loopback_gets(runtime):
    report = diagnose(runtime.root, session=runtime.session, now=NOW)
    assert report["status"] == "running"
    assert report["universe"] == "NIFTY 500"
    assert report["target_symbols"] == ["TCS"]
    assert len(runtime.calls) == 5
    assert runtime.session.trust_env is False
    assert runtime.key not in str(report)


@pytest.mark.parametrize(
    "path,field,value,issue",
    [
        ("/paper/automation", "universe", "NIFTY 100", "nifty500_scope"),
        ("/paper/automation", "worker_running", False, "automation_worker_running"),
        ("/paper/automation", "last_checked_at", None, "automation_heartbeat_recent"),
        (
            "/paper/automation",
            "blockers",
            ["paper_auto_entry_disabled"],
            "no_entry_blockers",
        ),
        ("/paper/readiness", "kill_switch", True, "kill_switch_off"),
        ("/paper/readiness", "entry_storage_policy", {}, "storage_verified"),
        ("/paper/readiness", "automatic_monitor", {}, "quote_monitor_running"),
        (
            "/paper/strategy-monitor/readiness",
            "enabled",
            False,
            "strategy_monitor_enabled",
        ),
        (
            "/technical/multi-strategy/validation/status",
            "registry_version",
            "old",
            "nifty500_validation_complete",
        ),
        (
            "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true",
            "authenticated",
            False,
            "kite_authenticated",
        ),
        (
            "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true",
            "quote_status",
            "unavailable_or_stale",
            "fresh_market_quote",
        ),
    ],
)
def test_failed_requirements_are_reported_without_arming_trades(
    runtime, path, field, value, issue
):
    runtime.data[path][field] = value
    report = diagnose(runtime.root, session=runtime.session, now=NOW)
    assert report["status"] == "needs_attention"
    assert issue in report["issues"]


def test_a_busy_scan_does_not_hide_a_stale_heartbeat(runtime):
    auto = runtime.data["/paper/automation"]
    auto["last_checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
    assert (
        diagnose(runtime.root, session=runtime.session, now=NOW)["status"]
        == "needs_attention"
    )
    auto["busy"] = True
    report = diagnose(runtime.root, session=runtime.session, now=NOW)
    assert report["cycle_in_progress"] is True
    assert report["status"] == "needs_attention"
    assert "automation_heartbeat_recent" in report["issues"]


def test_off_and_after_hours_are_not_a_successful_trade_claim(runtime):
    auto = runtime.data["/paper/automation"]
    auto["enabled"] = False
    assert diagnose(runtime.root, session=runtime.session, now=NOW)["status"] == "off"
    auto["enabled"] = True
    late = NOW.replace(hour=18)
    auto["last_checked_at"] = late.isoformat()
    runtime.data[
        "/workspace/kite-trading-readiness?probe_quotes=true&probe_history=true"
    ]["quote_status"] = "unavailable_or_stale"
    report = diagnose(runtime.root, session=runtime.session, now=late)
    assert report["status"] == "waiting_for_market"
    assert report["market_entry_window_open"] is False


@pytest.mark.parametrize("status", [302, 401, 503])
def test_http_errors_and_redirects_are_sanitized(runtime, status):
    runtime.session.get = lambda *args, **kwargs: SimpleNamespace(status_code=status)
    report = diagnose(runtime.root, session=runtime.session, now=NOW)
    assert report["status"] == "backend_check_failed"
    assert report["http_status"] == status
    assert runtime.key not in str(report)


def test_connection_failure_does_not_echo_secrets(runtime):
    def fail(*args, **kwargs):
        raise requests.ConnectionError(runtime.key)

    runtime.session.get = fail
    report = diagnose(runtime.root, session=runtime.session, now=NOW)
    assert report["status"] == "backend_unavailable_or_invalid"
    assert runtime.key not in str(report)


def test_missing_key_is_not_created_and_no_network_request_is_sent(runtime):
    (runtime.root / "private" / "admin-key.txt").unlink()
    assert (
        diagnose(runtime.root, session=runtime.session, now=NOW)["status"]
        == "admin_key_unavailable"
    )
    assert not runtime.calls
    assert not (runtime.root / "private" / "admin-key.txt").exists()
