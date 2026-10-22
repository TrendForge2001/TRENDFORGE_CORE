"""Paper entries obey storage policy at the shared service boundary."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.database import initialize_database
from core.paper_storage_policy import paper_entry_storage_policy
from core.storage_config import storage_durability_diagnostics, storage_health
from services.paper_auto_entry_service import PaperAutoEntryService
from services.paper_trading_runtime import PaperTradingRuntime
from services.paper_trading_service import (
    PaperTradingDisabledError,
    PaperTradingKillSwitchError,
    PaperTradingService,
    PaperTradingStorageError,
)


NOW = datetime(2026, 10, 16, 10, 0)
SIMULATION_ENV = "TRENDFORGE_PAPER_ALLOW_EPHEMERAL_SIMULATION"


@pytest.fixture(autouse=True)
def isolated_storage_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in (
        "RENDER", "TRENDFORGE_PRODUCTION_RUNTIME", SIMULATION_ENV,
        "DATABASE_PATH", "TRENDFORGE_DATA_DIR", "TRENDFORGE_PERSISTENT_MOUNT",
        "TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES",
        "TRENDFORGE_PAPER_CAPITAL", "TRENDFORGE_PAPER_RISK_PER_TRADE_PERCENT",
        "TRENDFORGE_PAPER_MAX_DAILY_LOSS_PERCENT", "TRENDFORGE_PAPER_MAX_OPEN_POSITIONS",
        "TRENDFORGE_PAPER_MAX_CAPITAL_PER_TRADE_PERCENT", "TRENDFORGE_PAPER_MINIMUM_RR",
        "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_SCORE", "TRENDFORGE_PAPER_AUTO_ENTRY_MIN_CONFIDENCE",
        "TRENDFORGE_PAPER_AUTO_ENTRY_MAX_PER_SCAN", "TRENDFORGE_PAPER_AUTO_ENTRY_SIGNALS",
    ):
        monkeypatch.delenv(name, raising=False)


class Runtime:
    def __init__(self, database_path=None):
        self.open_calls = []
        self.portfolio = SimpleNamespace(positions={})
        self.trades = SimpleNamespace(
            db=SimpleNamespace(db_path=database_path),
            has_trade_on_entry_date=lambda *args: False,
            realized_pnl_for_entry_date=lambda *args: 0.0,
        )
        self.saved_kill = False

    def load_kill_switch(self):
        return self.saved_kill

    def save_kill_switch(self, enabled):
        self.saved_kill = bool(enabled)
        return True

    def open(self, order, now=None):
        self.open_calls.append(order)
        return len(self.open_calls)

    def snapshot(self):
        return {"positions": [], "open_positions": 0}

    @staticmethod
    def _can_open(now):
        return True


def service(runtime=None, **kwargs):
    return PaperTradingService(
        runtime or Runtime(), enabled=kwargs.get("enabled", True),
        environment_kill_switch=kwargs.get("environment_kill_switch", False),
    )


def order(symbol="TCS"):
    return SimpleNamespace(
        symbol=symbol, side="BUY", quantity=1, price=100.0,
        stoploss=95.0, target2=110.0,
    )


def completed_scan():
    return {
        "outcome": "completed",
        "top_picks": [{
            "symbol": "TCS", "execution_eligible": True,
            "ranking_score": 95.0, "confidence": 95.0,
            "signal": {"signal": "BUY", "entry": 100.0, "stoploss": 95.0,
                       "target2": 110.0, "overall_score": 95.0, "confidence": 95.0},
        }],
    }


@pytest.mark.parametrize("production_flag", ["RENDER", "TRENDFORGE_PRODUCTION_RUNTIME"])
def test_production_default_blocks_real_service_before_runtime_open(monkeypatch, production_flag):
    monkeypatch.setenv(production_flag, "true")
    paper = service()

    assert paper.can_open_new_positions is False
    assert paper.health()["entry_storage_policy"]["reason"] == "persistent_storage_required"
    with pytest.raises(PaperTradingStorageError):
        paper.open(order(), now=NOW)
    assert paper.runtime.open_calls == []


def test_general_ephemeral_admin_write_override_cannot_enable_paper_entries(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_ALLOW_EPHEMERAL_ADMIN_WRITES", "true")
    paper = service()
    with pytest.raises(PaperTradingStorageError):
        paper.open(order(), now=NOW)
    assert paper.runtime.open_calls == []


def test_explicit_ephemeral_mode_allows_paper_but_never_claims_durability(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(SIMULATION_ENV, "true")
    paper = service()

    result = paper.open(order(), now=NOW)

    assert result["status"] == "opened"
    policy = result["entry_storage_policy"]
    assert policy["mode"] == "ephemeral_simulation"
    assert policy["ephemeral_simulation"] is True
    assert policy["verified_persistent"] is False
    assert "lost" in policy["message"]
    assert result["broker_orders_allowed"] is False


@pytest.mark.parametrize("enabled,killed,error", [
    (False, False, PaperTradingDisabledError),
    (True, True, PaperTradingKillSwitchError),
])
def test_ephemeral_opt_in_cannot_bypass_existing_entry_controls(monkeypatch, enabled, killed, error):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(SIMULATION_ENV, "true")
    paper = service(enabled=enabled, environment_kill_switch=killed)
    with pytest.raises(error):
        paper.open(order(), now=NOW)
    assert paper.can_open_new_positions is False
    assert paper.runtime.open_calls == []


def test_local_development_entry_behavior_is_preserved_without_durable_claim(monkeypatch):
    monkeypatch.setattr(
        "core.paper_storage_policy.storage_health",
        lambda: pytest.fail("Local simulation must not require a production disk probe"),
    )
    paper = service()
    result = paper.open(order(), now=NOW)
    assert result["entry_storage_policy"]["mode"] == "local_simulation"
    assert result["entry_storage_policy"]["verified_persistent"] is False
    assert len(paper.runtime.open_calls) == 1


def test_ephemeral_opt_in_is_rechecked_for_every_entry(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(SIMULATION_ENV, "true")
    paper = service()
    paper.open(order(), now=NOW)
    monkeypatch.delenv(SIMULATION_ENV)
    with pytest.raises(PaperTradingStorageError):
        paper.open(order("INFY"), now=NOW)
    assert len(paper.runtime.open_calls) == 1


def _mounted_configuration(monkeypatch):
    mount = "/mnt/trendforge-policy-fixture"
    target = mount + "/database/paper.db"
    state = {"mounted": True}
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_PATH", target)
    monkeypatch.setenv("TRENDFORGE_PERSISTENT_MOUNT", mount)
    monkeypatch.setenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED", "true")
    monkeypatch.setattr("core.storage_config.os.path.ismount", lambda path: state["mounted"] and path == mount)
    return target, state


def test_mount_recovery_policy_agrees_across_diagnostics_and_entry(monkeypatch):
    target, _ = _mounted_configuration(monkeypatch)
    paper = service(Runtime(target))

    assert storage_health()["verified_persistent"] is True
    assert storage_durability_diagnostics()["durability_verified"] is True
    assert paper.entry_storage_policy()["mode"] == "durable"
    assert paper.can_open_new_positions is True

    monkeypatch.delenv("TRENDFORGE_STORAGE_RECOVERY_VERIFIED")

    assert storage_health()["verified_persistent"] is False
    assert storage_durability_diagnostics()["durability_verified"] is False
    assert paper.can_open_new_positions is False
    with pytest.raises(PaperTradingStorageError):
        paper.open(order(), now=NOW)
    assert paper.runtime.open_calls == []


def test_mount_loss_revokes_admission_after_a_successful_entry(monkeypatch):
    target, state = _mounted_configuration(monkeypatch)
    paper = service(Runtime(target))
    paper.open(order(), now=NOW)

    state["mounted"] = False

    assert paper.can_open_new_positions is False
    assert storage_durability_diagnostics()["durability_verified"] is False
    with pytest.raises(PaperTradingStorageError):
        paper.open(order("INFY"), now=NOW)
    assert len(paper.runtime.open_calls) == 1


def test_runtime_database_mismatch_blocks_even_with_simulation_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "canonical.db"))
    monkeypatch.setenv(SIMULATION_ENV, "true")
    monkeypatch.setattr("core.paper_storage_policy.storage_health", lambda: {"verified_persistent": True})
    paper = service(Runtime(str(tmp_path / "other.db")))

    assert paper.entry_storage_policy()["reason"] == "runtime_database_mismatch"
    with pytest.raises(PaperTradingStorageError):
        paper.open(order(), now=NOW)
    assert paper.runtime.open_calls == []


def test_canonical_symlink_alias_is_same_runtime_database(monkeypatch, tmp_path):
    actual = tmp_path / "actual.db"
    actual.touch()
    alias = tmp_path / "alias.db"
    alias.symlink_to(actual)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DATABASE_PATH", str(alias))
    monkeypatch.setattr("core.paper_storage_policy.storage_health", lambda: {"verified_persistent": True})
    policy = paper_entry_storage_policy(runtime_database_path=str(actual))
    assert policy["entry_allowed"] is True
    assert policy["mode"] == "durable"


def test_storage_probe_failure_is_safe_and_cannot_be_bypassed_by_simulation(monkeypatch):
    sentinel = "PRIVATE_STORAGE_CREDENTIAL"
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(SIMULATION_ENV, "true")

    def unavailable():
        raise RuntimeError(sentinel)

    monkeypatch.setattr("core.paper_storage_policy.storage_health", unavailable)
    paper = service()
    policy = paper.entry_storage_policy()
    assert policy["entry_allowed"] is False
    assert policy["reason"] == "storage_verification_unavailable"
    with pytest.raises(PaperTradingStorageError) as error:
        paper.open(order(), now=NOW)
    assert sentinel not in json.dumps(policy)
    assert sentinel not in str(error.value)
    assert paper.runtime.open_calls == []


def test_durable_entry_requires_persistent_kill_control_support(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr("core.paper_storage_policy.storage_health", lambda: {"verified_persistent": True})
    runtime = Runtime()
    runtime.load_kill_switch = None
    runtime.save_kill_switch = None
    paper = service(runtime)
    assert paper.entry_storage_policy()["reason"] == "kill_control_storage_unavailable"
    with pytest.raises(PaperTradingStorageError):
        paper.open(order(), now=NOW)
    assert runtime.open_calls == []


def test_real_runtime_does_not_write_new_position_after_storage_revocation(monkeypatch, tmp_path):
    target = tmp_path / "paper.db"
    monkeypatch.setenv("DATABASE_PATH", str(target))
    monkeypatch.setenv("RENDER", "true")
    initialize_database()
    state = {"verified": True}
    monkeypatch.setattr(
        "core.paper_storage_policy.storage_health", lambda: {"verified_persistent": state["verified"]},
    )
    runtime = PaperTradingRuntime()
    paper = service(runtime)
    try:
        paper.open(order(), now=NOW)
        assert Path(runtime.trades.db.db_path).resolve() == target.resolve()
        state["verified"] = False
        with pytest.raises(PaperTradingStorageError):
            paper.open(order("INFY"), now=NOW)
        rows = runtime.trades.db.fetchall("SELECT symbol FROM trade_history")
        assert [row["symbol"] for row in rows] == ["TCS"]
    finally:
        paper.close()


def test_background_auto_entry_rejects_storage_before_runtime_open(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    paper = service()
    auto = PaperAutoEntryService(paper, enabled=True)
    result = auto.process_scan(completed_scan(), run_id="storage-blocked", execute_requested=True, now=NOW)

    assert result["status"] == "blocked"
    assert result["reason"] == "paper_trading_not_ready"
    assert result["opened"] == []
    assert paper.runtime.open_calls == []
    assert auto.execution_attempts == 0


def test_storage_rechecked_between_auto_entry_readiness_and_execution(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    reports = iter([True, False])
    monkeypatch.setattr(
        "core.paper_storage_policy.storage_health",
        lambda: {"verified_persistent": next(reports, False)},
    )
    paper = service()
    auto = PaperAutoEntryService(paper, enabled=True)
    result = auto.process_scan(completed_scan(), run_id="storage-revoked", execute_requested=True, now=NOW)

    assert result["status"] == "no_entries"
    assert result["opened_count"] == 0
    assert result["evaluations"][0]["reasons"] == ["paper_open_failed"]
    assert paper.runtime.open_calls == []
    assert auto.execution_attempts == 1
