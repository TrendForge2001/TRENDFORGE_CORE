"""Server-side evidence must be authenticated, read-only and fail closed."""

import json
from copy import deepcopy
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace
from urllib.error import URLError
from zoneinfo import ZoneInfo

import pytest

from scanner.strategy_registry import REGISTRY_VERSION, list_strategies
from services.paper_startup_probe import PATHS, paper_session_probe

NOW = datetime(2026, 11, 16, 10, 15, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def source(monkeypatch):
    key = "private-startup-diagnostic-key-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    monkeypatch.setenv("PORT", "10000")
    strategy_id = next(
        row["strategy_id"] for row in list_strategies() if row["paper_eligible"]
    )
    payloads = {
        "automation": {
            "enabled": False,
            "worker_running": True,
            "last_checked_at": NOW.isoformat(),
            "blockers": [],
            "settings_saved": True,
            "paper_only": True,
            "broker_orders_allowed": False,
            "universe": "NIFTY 500",
            "target_strategy_ids": [strategy_id],
            "last_error": None,
        },
        "paper": {
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
        "strategy_monitor": {"enabled": True},
        "validation": {
            "status": "completed",
            "run_id": "private-validation-run",
            "registry_version": REGISTRY_VERSION,
            "request": {
                "universes": ["NIFTY 500"],
                "modes": ["intraday", "swing", "positional"],
                "source": "all",
            },
            "strategy_validation": [
                {
                    "strategy_id": strategy_id,
                    "mode": "intraday",
                    "registry_paper_eligible": True,
                    "promotion_status": "ELIGIBLE_FOR_REVIEW",
                    "universe_gates": [{"universe": "NIFTY 500", "status": "PASS"}],
                }
            ],
        },
        "kite": {
            "authenticated": True,
            "quote_status": "fresh",
            "history_status": "available",
            "indicator_status": "calculated",
            "broker_orders_allowed": False,
        },
    }
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            assert request.method == "GET"
            assert request.full_url.startswith("http://127.0.0.1:10000/")
            assert request.get_header("X-trendforge-admin-key") == key
            assert timeout == 20
            name = next(
                name for name, path in PATHS.items() if request.full_url.endswith(path)
            )
            calls.append(name)
            body = payloads[name]
            if isinstance(body, Exception):
                raise body
            response = BytesIO(json.dumps(body).encode())
            response.status = 200
            return response

    return SimpleNamespace(key=key, data=payloads, calls=calls, opener=Opener())


def test_probe_reads_real_control_endpoints_without_activating_automation(source):
    before = deepcopy(source.data)
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert report["status"] == "checks_passed"
    assert report["failed_checks"] == []
    assert report["eligible_strategy_pairs"] == 1
    assert report["automation_enabled"] is False
    assert report["automation_changed"] is False
    assert report["probe_orders_submitted"] == 0
    assert report["candidate_risk_admission"] == "required_before_every_fill"
    assert source.calls == list(PATHS)
    assert source.data == before
    assert source.key not in json.dumps(report)


@pytest.mark.parametrize(
    "field,value,check",
    [
        ("quote_status", "unavailable_or_stale", "fresh_market_quote"),
        ("authenticated", False, "kite_authenticated"),
        ("history_status", "unavailable_or_invalid", "completed_history_available"),
        ("indicator_status", "unavailable", "scanner_indicators_calculated"),
    ],
)
def test_market_data_failure_is_not_treated_as_readiness(source, field, value, check):
    source.data["kite"][field] = value
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert report["status"] == "needs_attention"
    assert check in report["failed_checks"]


@pytest.mark.parametrize(
    "change",
    [
        "old_registry",
        "wrong_scope",
        "incomplete",
        "failed_gate",
        "missing_gate",
        "different_strategy",
    ],
)
def test_completed_job_does_not_approve_an_unvalidated_selected_strategy(
    source, change
):
    validation = source.data["validation"]
    if change == "old_registry":
        validation["registry_version"] = "old"
    elif change == "wrong_scope":
        validation["request"]["universes"] = ["NIFTY 100"]
    elif change == "incomplete":
        validation["status"] = "running"
    elif change == "failed_gate":
        validation["strategy_validation"][0]["universe_gates"][0]["status"] = "FAIL"
    elif change == "missing_gate":
        validation["strategy_validation"][0]["universe_gates"] = None
    else:
        source.data["automation"]["target_strategy_ids"] = ["unvalidated-strategy"]
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert report["status"] == "needs_attention"
    assert "validated_strategy_pair_available" in report["failed_checks"]


def test_worker_monitor_and_storage_failures_remain_independent(source):
    source.data["automation"].update(
        worker_running=False, last_checked_at=None, blockers=[source.key]
    )
    source.data["paper"]["entry_storage_policy"]["verified_persistent"] = False
    source.data["paper"]["automatic_monitor"]["running"] = False
    source.data["strategy_monitor"]["last_error"] = source.key
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert set(report["failed_checks"]) >= {
        "storage_verified",
        "automation_worker_running",
        "recent_worker_heartbeat",
        "quote_exit_monitor_running",
        "monitors_without_error",
        "no_entry_blockers",
    }
    assert source.key not in json.dumps(report)


def test_unauthorized_or_failed_reads_are_not_green_or_leaked(source):
    source.data["validation"] = URLError(source.key)
    source.data["kite"] = {
        "authenticated": False,
        "quote_status": source.key,
        "history_status": source.key,
    }
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert report["failed_reads"] == ["validation"]
    assert report["quote_status"] == report["history_status"] == "unknown"
    assert report["status"] == "needs_attention"
    assert source.key not in json.dumps(report)


def test_preopen_report_does_not_approve_early_entries(source):
    now = NOW.replace(hour=9, minute=10)
    source.data["automation"]["last_checked_at"] = now.isoformat()
    report = paper_session_probe(opener=source.opener, now=now)
    assert report["status"] == "needs_attention"
    assert report["failed_checks"] == ["entry_window_open"]


def test_no_credentials_means_no_request(source, monkeypatch):
    monkeypatch.delenv("TRENDFORGE_ADMIN_API_KEY")
    report = paper_session_probe(opener=source.opener, now=NOW)
    assert report["status"] == "admin_key_unavailable"
    assert source.calls == []
