"""Paper controls fail closed without hiding existing-position safety actions."""
from copy import deepcopy
from pathlib import Path

import pytest

from webapp.paper_policy import (
    paper_entry_allowed,
    paper_execution_requested,
    paper_policy_notice,
)


def readiness(mode="durable", *, can_open=True):
    return {
        "can_open_new_positions": can_open,
        "entry_storage_policy": {
            "entry_allowed": mode != "blocked",
            "mode": mode,
            "production": mode != "local_simulation",
            "verified_persistent": mode == "durable",
            "ephemeral_simulation": mode == "ephemeral_simulation",
            "reason": "operator_verified",
            "message": "Backend message",
        },
    }


@pytest.mark.parametrize("mode", ["durable", "ephemeral_simulation", "local_simulation"])
def test_allowed_storage_mode_still_requires_runtime_admission(mode):
    report = readiness(mode)
    assert paper_entry_allowed(report) is True
    assert paper_execution_requested(True, report) is True
    assert paper_execution_requested(False, report) is False
    report["can_open_new_positions"] = False
    assert paper_entry_allowed(report) is False
    assert paper_execution_requested(True, report) is False


def test_changed_policy_clears_effect_of_stale_enabled_toggle():
    report = readiness()
    old_widget_value = True
    assert paper_execution_requested(old_widget_value, report) is True
    report["entry_storage_policy"] = readiness("blocked")["entry_storage_policy"]
    assert paper_execution_requested(old_widget_value, report) is False
    assert paper_entry_allowed(report) is False
    level, message = paper_policy_notice(report)
    assert level == "warning"
    assert "blocked until storage is verified" in message
    assert "monitored and exited" in message
    assert "kill controls remain available" in message


@pytest.mark.parametrize("report", [
    None, {}, [], "ready",
    {"can_open_new_positions": True},
    {"can_open_new_positions": True, "entry_storage_policy": []},
])
def test_unavailable_readiness_disables_new_entries(report):
    assert paper_entry_allowed(report) is False
    assert paper_execution_requested(True, report) is False
    level, message = paper_policy_notice(report)
    assert level == "warning"
    assert "readiness is unavailable" in message
    assert "kill controls remain available" in message


@pytest.mark.parametrize("field,value", [
    ("entry_allowed", "true"), ("production", "false"),
    ("verified_persistent", 1), ("ephemeral_simulation", None),
    ("mode", "unknown"), ("mode", []),
])
def test_malformed_policy_is_not_treated_as_permission(field, value):
    report = readiness()
    report["entry_storage_policy"][field] = value
    assert paper_entry_allowed(report) is False
    assert paper_execution_requested(True, report) is False


@pytest.mark.parametrize("mode,field,value", [
    ("durable", "verified_persistent", False),
    ("ephemeral_simulation", "ephemeral_simulation", False),
    ("local_simulation", "production", True),
])
def test_inconsistent_storage_mode_is_not_treated_as_permission(mode, field, value):
    report = readiness(mode)
    report["entry_storage_policy"][field] = value
    assert paper_entry_allowed(report) is False


def test_ephemeral_simulation_warning_is_explicit_and_does_not_copy_backend_text():
    report = readiness("ephemeral_simulation")
    report["entry_storage_policy"]["message"] = "SECRET_BACKEND_ERROR"
    original = deepcopy(report)
    level, message = paper_policy_notice(report)
    assert level == "warning"
    assert "Ephemeral simulation" in message
    assert "positions, history and risk state may be lost" in message
    assert "SECRET_BACKEND_ERROR" not in message
    assert report == original


@pytest.mark.parametrize("requested", ["true", 1, None, [], {}])
def test_only_explicit_true_can_request_paper_execution(requested):
    assert paper_execution_requested(requested, readiness()) is False


def test_unavailable_saved_kill_state_blocks_new_entry_controls():
    report = readiness()
    report["kill_switch_storage"] = {"status": "unavailable", "reference": "abc123"}
    assert paper_entry_allowed(report) is False
    assert paper_execution_requested(True, report) is False


@pytest.mark.parametrize("saved_kill_unavailable", [False, True])
def test_paper_page_disables_entry_without_disabling_emergency_controls(monkeypatch, saved_kill_unavailable):
    from streamlit.testing.v1 import AppTest

    report = readiness("durable" if saved_kill_unavailable else "blocked", can_open=False)
    if saved_kill_unavailable:
        report["kill_switch_storage"] = {"status": "unavailable", "reference": "abc123"}
    calls = []

    class Client:
        def get_json(self, path):
            return report if path == "/paper/readiness" else {}

        def post_json(self, path, payload):
            calls.append((path, payload))
            return {"status": "ok"}

    monkeypatch.setattr("webapp.runtime.api_client", lambda: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    page_path = Path(__file__).resolve().parents[1] / "webapp/pages/paper_trading.py"
    page = AppTest.from_file(page_path).run(timeout=15)
    assert not page.exception
    buttons = {button.label: button for button in page.button}
    assert buttons["Open paper position"].disabled is True
    assert buttons["Enable kill switch"].disabled is False
    assert buttons["Disable kill switch"].disabled is False
    assert buttons["Run monitor tick"].disabled is False
    if saved_kill_unavailable:
        assert any("Saved kill-switch state is unavailable" in item.value for item in page.warning)
    buttons["Enable kill switch"].click().run(timeout=15)
    assert not page.exception
    assert calls == [("/paper/kill-switch", {"enabled": True})]
    monitor = next(button for button in page.button if button.label == "Run monitor tick")
    monitor.click().run(timeout=15)
    assert not page.exception
    assert calls[-1] == ("/paper/monitor/tick", {})
    assert all(path != "/paper/open" for path, _ in calls)
