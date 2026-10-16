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


def test_external_tick_is_not_in_broad_admin_route_scope():
    assert not _protected_admin_request(
        "POST",
        "/operations/external-tick",
    )


def test_morning_workflow_uses_narrow_scheduler_secret_only():
    workflow = text(
        ".github/workflows/market-day-morning.yml"
    )

    assert 'cron: "15,25,35,45 3 * * *"' in workflow
    assert "scripts/operations_wakeup.py" in workflow
    assert "--expect morning" in workflow
    assert "vars.TRENDFORGE_SCHEDULER_URL" in workflow
    assert "secrets.TRENDFORGE_SCHEDULER_API_KEY" in workflow
    assert "TRENDFORGE_ADMIN_API_KEY" not in workflow


def test_eod_workflow_uses_narrow_scheduler_secret_only():
    workflow = text(
        ".github/workflows/market-day-eod.yml"
    )

    assert 'cron: "15,25,35,45 10 * * *"' in workflow
    assert "scripts/operations_wakeup.py" in workflow
    assert "--expect eod" in workflow
    assert "vars.TRENDFORGE_SCHEDULER_URL" in workflow
    assert "secrets.TRENDFORGE_SCHEDULER_API_KEY" in workflow
    assert "TRENDFORGE_ADMIN_API_KEY" not in workflow


def test_active_render_manifest_is_not_turned_into_a_cron_service():
    manifest = text("render.yaml")

    assert "name: trendforge-core" in manifest
    assert "type: web" in manifest
    assert "type: cron" not in manifest
    assert "TRENDFORGE_SCHEDULER_API_KEY" not in manifest
