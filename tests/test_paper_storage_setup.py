"""Storage diagnosis must identify missing infrastructure without unlocking it."""

import json

import pytest

from core.storage_config import storage_health
from services import paper_storage_setup as setup


def environment(**changes):
    return {
        "DATABASE_PATH": "/var/data/trendforge.db",
        "TRENDFORGE_PERSISTENT_MOUNT": "/var/data",
        "TRENDFORGE_STORAGE_RECOVERY_VERIFIED": "true",
        **changes,
    }


def test_a_recovery_flag_alone_cannot_make_an_unmounted_disk_durable(monkeypatch):
    monkeypatch.setattr("core.storage_config.os.path.ismount", lambda _: False)
    report = storage_health(environment())
    monkeypatch.setattr(setup, "storage_health", lambda: report)
    status = setup.paper_storage_setup()
    assert status["status"] == "setup_required"
    assert status["verified"] is False
    failed = [row["label"] for row in status["checks"] if row["passed"] is False]
    assert failed == ["Persistent disk is actually mounted"]


@pytest.mark.parametrize(
    "changes,label",
    [
        (
            {"TRENDFORGE_STORAGE_RECOVERY_VERIFIED": "false"},
            "Database recovery after restart confirmed",
        ),
        (
            {"DATABASE_PATH": "/opt/render/project/src/database/trendforge.db"},
            "Database is located on the disk",
        ),
        ({"DATABASE_PATH": "database/trendforge.db"}, "Database uses an absolute path"),
        ({"DATABASE_PATH": ""}, "Database location configured"),
        ({"TRENDFORGE_PERSISTENT_MOUNT": ""}, "Persistent disk mount configured"),
    ],
)
def test_missing_configuration_reports_a_specific_failed_check(
    monkeypatch, changes, label
):
    monkeypatch.setattr("core.storage_config.os.path.ismount", lambda _: True)
    report = storage_health(environment(**changes))
    monkeypatch.setattr(setup, "storage_health", lambda: report)
    status = setup.paper_storage_setup()
    assert status["verified"] is False
    assert any(
        row["label"] == label and row["passed"] is False for row in status["checks"]
    )


def test_ready_requires_mount_path_and_recovery_and_diagnostics_are_read_only(
    monkeypatch,
):
    monkeypatch.setattr("core.storage_config.os.path.ismount", lambda _: True)
    report = storage_health(environment())
    original = dict(report)
    monkeypatch.setattr(setup, "storage_health", lambda: report)
    status = setup.paper_storage_setup()
    assert status["verified"] is True
    assert all(row["passed"] for row in status["checks"])
    assert report == original


def test_storage_inspection_failure_is_sanitized(monkeypatch):
    def unavailable():
        raise RuntimeError("PRIVATE_STORAGE_ERROR")

    monkeypatch.setattr(setup, "storage_health", unavailable)
    status = setup.paper_storage_setup()
    assert status == {"status": "unavailable", "checks": [], "verified": False}
    assert "PRIVATE_STORAGE_ERROR" not in json.dumps(status)


@pytest.mark.parametrize("verified,exit_code", [(True, 0), (False, 1)])
def test_read_only_cli_reports_failure_until_verified(
    monkeypatch, capsys, verified, exit_code
):
    from scripts import check_paper_storage

    monkeypatch.setattr(
        check_paper_storage, "paper_storage_setup", lambda: {"verified": verified}
    )
    assert check_paper_storage.main() == exit_code
    assert json.loads(capsys.readouterr().out) == {"verified": verified}


def test_blocked_storage_ui_explains_disk_and_recovery_without_hiding_controls():
    from streamlit.testing.v1 import AppTest

    source = """from webapp.paper_policy import render_paper_storage_setup
import streamlit as st
render_paper_storage_setup({
    "verified": False,
    "checks": [{"label": "Persistent disk is actually mounted", "passed": False}],
})
st.button("Activate paper kill switch")
"""
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert any(
        "Paid compute and disk charges apply" in item.value for item in app.markdown
    )
    assert any(
        "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION=false" in item.value
        for item in app.code
    )
    assert all(
        "TRENDFORGE_STORAGE_RECOVERY_VERIFIED=true" not in item.value
        for item in app.code
    )
    assert not app.button[0].disabled
