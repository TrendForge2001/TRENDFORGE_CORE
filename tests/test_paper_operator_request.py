"""One-use paper operator command, with no broker calls or external data."""

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from core.database import initialize_database
from database.repositories.strategy_runtime_state_repository import (
    StrategyRuntimeStateRepository,
)
from scanner.strategy_registry import REGISTRY_VERSION
from services.paper_operator_request import (
    BASE_CHECKS,
    ENV,
    run_paper_operator_request,
    start_paper_operator_request,
)
from tests.test_saved_strategy_automation import build

NOW = datetime(2026, 11, 17, 4, 0, tzinfo=UTC)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "false")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    path = str(tmp_path / "state.db")
    initialize_database(path)
    repo = StrategyRuntimeStateRepository(db_path=path)
    auto = {
        "universe": "NIFTY 100",
        "target_symbols": ["RELIANCE"],
        "target_strategy_ids": ["tf_ema9_26_bullish_pivot"],
        "assume_short_borrow": False,
        "control_generation": 0,
        "enabled": False,
        "paper_only": True,
        "broker_orders_allowed": False,
        "account_policy": {"capital": 250000},
    }
    env = SimpleNamespace(
        repository=repo,
        CONFIG_KEY="paper.automation.config.v1",
        auto=auto,
        requests=[],
        starts=[],
        sleeps=[],
        validation={},
        now=NOW,
        checks={
            **dict.fromkeys(BASE_CHECKS, True),
            "storage_verified": True,
            "paper_only": True,
            "kill_switch_off": True,
            "recent_worker_heartbeat": True,
            "entry_window_open": True,
            "fresh_market_quote": True,
            "automation_worker_running": True,
            "current_scope_validation_complete": True,
            "validated_strategy_pair_available": True,
        },
    )
    env.command = {
        "id": "a" * 32,
        "action": "validate_then_start",
        "registry_version": REGISTRY_VERSION,
        "authorized_at": (NOW - timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "confirm_render_executor": True,
    }
    env.status = lambda: deepcopy(env.auto)

    def configure(enabled, **kwargs):
        assert kwargs["expected_control_generation"] == env.auto["control_generation"]
        assert kwargs["confirm_render_executor"] is True
        env.starts.append((enabled, kwargs))
        env.auto.update(
            enabled=enabled, control_generation=env.auto["control_generation"] + 1
        )

    def validate(request):
        env.requests.append(deepcopy(request))
        env.validation = {
            "status": "completed",
            "request": request,
            "run_id": "test-run",
            "registry_version": REGISTRY_VERSION,
        }
        return deepcopy(env.validation)

    async def sleep(seconds):
        env.sleeps.append(seconds)
        env.now += timedelta(seconds=seconds)

    def readiness():
        return {
            "checks": deepcopy(env.checks),
            "eligible_strategy_pairs": 2,
            "automation_enabled": env.auto["enabled"],
            "failed_checks": [key for key, passed in env.checks.items() if not passed],
        }

    env.configure, env.validate, env.sleep, env.readiness = (
        configure,
        validate,
        sleep,
        readiness,
    )
    env.run = lambda: asyncio.run(
        run_paper_operator_request(
            json.dumps(env.command),
            automation_getter=lambda: env,
            validation_getter=lambda: deepcopy(env.validation),
            validation_starter=env.validate,
            readiness=env.readiness,
            sleep=env.sleep,
            clock=lambda: env.now,
        )
    )
    env.receipt = lambda: (
        repo.load_state("paper.operator:" + env.command["id"]) or {}
    ).get("payload", {})
    yield env
    repo.close()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert start_paper_operator_request() is None


def test_full_validation_then_start_preserves_scope_and_capital_once(setup):
    env = setup
    env.run()
    assert env.requests == [
        {
            "universes": ["NIFTY 100"],
            "modes": ["intraday", "positional", "swing"],
            "source": "all",
            "limit": None,
            "strategy_ids": None,
            "capital": 250000,
            "chunk_size": 5,
            "force_refresh_universes": False,
        }
    ]
    assert len(env.starts) == 1
    assert env.starts[0][1]["symbols"] == ["RELIANCE"]
    assert env.starts[0][1]["strategy_ids"] == env.auto["target_strategy_ids"]
    assert env.receipt()["phase"] == "started"
    env.auto.update(enabled=False, control_generation=0)  # a fresh process
    env.run()
    assert len(env.starts) == 1
    assert env.auto["enabled"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"confirm_render_executor": False},
        {"registry_version": "old"},
        {"expires_at": NOW.isoformat()},
        {"extra": "not accepted"},
        {"authorized_at": "2026-11-17T04:00:00"},
    ],
)
def test_invalid_authorization_never_runs(setup, change):
    env = setup
    env.command.update(change)
    env.run()
    assert not env.requests and not env.starts and not env.receipt()


def test_pc_or_read_only_execution_never_runs(setup, monkeypatch):
    monkeypatch.setenv("TRENDFORGE_CLOUD_READ_ONLY", "true")
    setup.run()
    assert not setup.requests and not setup.starts


@pytest.mark.parametrize("check", ["paper_only", "storage_verified", "kill_switch_off"])
def test_critical_failure_never_starts(setup, check):
    setup.checks[check] = False
    setup.run()
    assert not setup.requests and not setup.starts


def test_no_eligible_pair_leaves_off(setup):
    setup.checks["validated_strategy_pair_available"] = False
    setup.run()
    assert setup.requests and not setup.starts
    assert setup.receipt()["phase"] == "validation_rejected"


def test_waits_for_market_and_fresh_quote_before_start(setup):
    env = setup
    env.checks.update(entry_window_open=False, fresh_market_quote=False)
    original = env.sleep

    async def opening(seconds):
        if env.receipt().get("phase") == "awaiting_ready":
            assert not env.auto["enabled"]
            env.checks.update(entry_window_open=True, fresh_market_quote=True)
        await original(seconds)

    env.sleep = opening
    env.run()
    assert env.receipt()["phase"] == "started"


def test_expiry_while_waiting_cannot_start_later(setup):
    setup.checks["entry_window_open"] = False
    setup.command["expires_at"] = (NOW + timedelta(seconds=65)).isoformat()
    setup.run()
    assert setup.receipt()["phase"] == "expired"
    assert not setup.starts


def test_stop_during_validation_supersedes_pending_start(setup):
    env = setup
    original = env.sleep

    async def stop(seconds):
        env.auto["control_generation"] += 1
        await original(seconds)

    env.sleep = stop
    env.run()
    assert env.receipt()["phase"] == "superseded" and not env.starts


def test_newer_manual_stop_before_deploy_cancels_command(setup):
    env = setup
    env.repository.save_state(
        env.CONFIG_KEY, "paper_automation_config", {"updated_at": NOW.isoformat()}
    )
    env.run()
    assert not env.starts and not env.requests


def test_capital_change_cancels_pending_start(setup):
    env = setup
    original = env.sleep

    async def changed(seconds):
        env.auto["account_policy"]["capital"] = 999000
        await original(seconds)

    env.sleep = changed
    env.run()
    assert env.receipt()["phase"] == "superseded" and not env.starts


def test_limited_validation_is_replaced_by_full_validation(setup):
    env = setup
    env.validate(
        {"universes": ["NIFTY 100"], "modes": ["swing"], "source": "all", "limit": 25}
    )
    env.requests.clear()
    env.run()
    assert len(env.requests) == 1 and env.requests[0]["limit"] is None
    assert env.receipt()["phase"] == "started"


def test_failed_validation_never_starts_and_does_not_log_provider_details(
    setup, caplog
):
    env = setup

    def failed(request):
        env.validation = {"status": "failed", "error": "private-account-secret"}
        return env.validation

    env.validate = failed
    env.run()
    assert env.receipt()["phase"] == "validation_failed"
    assert not env.starts and "private-account-secret" not in caplog.text


def test_cancellation_during_validation_cannot_enable_later(setup):
    env = setup

    async def cancel(seconds):
        raise asyncio.CancelledError

    env.sleep = cancel
    with pytest.raises(asyncio.CancelledError):
        env.run()
    assert env.receipt()["phase"] == "interrupted"
    env.run()
    assert not env.starts


def test_durable_claim_is_atomic_across_connections(setup):
    env = setup
    second = StrategyRuntimeStateRepository(db_path=env.repository.db.db_path)
    try:
        assert env.repository.claim_state(
            "command:test", "operator", {"phase": "claimed"}
        )
        assert not second.claim_state(
            "command:test", "operator", {"phase": "overwrite"}
        )
        assert second.load_state("command:test")["payload"]["phase"] == "claimed"
    finally:
        second.close()


def test_real_automation_start_cas_rejects_stop_during_pending_validation(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    env = build()
    generation = env.service.status()["control_generation"]
    env.service.configure(False)
    with pytest.raises(ValueError, match="superseded"):
        env.service.configure(True, expected_control_generation=generation)
    assert not env.service.status()["enabled"] and not env.scans


def test_missing_readiness_checks_fail_closed(setup):
    del setup.checks["quote_exit_monitor_running"]
    setup.run()
    assert not setup.starts and not setup.requests
    assert setup.receipt()["phase"] == "blocked"


def test_receipt_storage_error_cannot_start(setup, monkeypatch):
    def failed(*args, **kwargs):
        raise OSError("private-storage-location")

    monkeypatch.setattr(setup.repository, "claim_state", failed)
    setup.run()
    assert not setup.starts and not setup.requests


def test_running_validation_is_awaited_without_start(setup):
    env = setup

    def running(request):
        env.validation = {
            "status": "running",
            "request": request,
            "run_id": "running-test",
            "progress": {"progress_pct": 25},
        }
        return env.validation

    env.validate = running
    env.command["expires_at"] = (NOW + timedelta(seconds=65)).isoformat()
    env.run()
    assert not env.starts and env.receipt()["phase"] == "expired"


def test_stop_at_final_configure_boundary_is_not_overridden(setup):
    env = setup

    def stop_then_configure(enabled, **kwargs):
        env.auto["control_generation"] += 1
        raise ValueError("A newer paper control command superseded this start")

    env.configure = stop_then_configure
    env.run()
    assert not env.auto["enabled"] and not env.starts


def test_on_is_verified_after_start_before_confirming(setup):
    env = setup
    original = env.readiness

    def stopped_after_start():
        result = original()
        if env.starts:
            env.auto.update(enabled=False, control_generation=2)
            result["automation_enabled"] = False
        return result

    env.readiness = stopped_after_start
    env.run()
    assert env.receipt()["phase"] == "start_needs_attention"
    assert len(env.starts) == 1 and not env.auto["enabled"]
