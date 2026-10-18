from __future__ import annotations

from pathlib import Path

from api.production_runtime import (
    _protected_admin_request,
)


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(
        encoding="utf-8"
    )


def test_morning_post_window_audit_uses_narrow_scheduler_secret():
    workflow = text(
        ".github/workflows/market-day-morning-audit.yml"
    )

    assert 'cron: "55 3 * * *"' in workflow
    assert 'cron: "5 4 * * *"' in workflow
    assert "scripts/operations_audit.py" in workflow
    assert "--expect morning" in workflow
    assert "vars.TRENDFORGE_SCHEDULER_URL" in workflow
    assert "secrets.TRENDFORGE_SCHEDULER_API_KEY" in workflow
    assert "TRENDFORGE_ADMIN_API_KEY" not in workflow
    assert "enabled=false" in workflow


def test_eod_post_window_audit_uses_narrow_scheduler_secret():
    workflow = text(
        ".github/workflows/market-day-eod-audit.yml"
    )

    assert 'cron: "55 10 * * *"' in workflow
    assert 'cron: "5 11 * * *"' in workflow
    assert "scripts/operations_audit.py" in workflow
    assert "--expect eod" in workflow
    assert "vars.TRENDFORGE_SCHEDULER_URL" in workflow
    assert "secrets.TRENDFORGE_SCHEDULER_API_KEY" in workflow
    assert "TRENDFORGE_ADMIN_API_KEY" not in workflow
    assert "enabled=false" in workflow


def test_external_audit_is_narrow_scope_not_admin_scope():
    assert not _protected_admin_request(
        "POST",
        "/operations/external-audit",
    )
    assert _protected_admin_request(
        "POST",
        "/operations/audit/run",
    )


def test_active_render_manifest_remains_web_service_only():
    manifest = text("render.yaml")

    assert "type: web" in manifest
    assert "type: cron" not in manifest
    assert "TRENDFORGE_SCHEDULER_API_KEY" not in manifest


def test_reliability_workflows_do_not_modify_test_workflow():
    tests = text(".github/workflows/tests.yml")
    assert "TrendForge Tests" in tests
    assert "production-dependency-audit" in tests
