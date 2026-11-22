"""Forward research can trade without relabelling historical failures as passes."""

import asyncio
import json
from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest

from scanner import approved_strategies as rules
from scanner.strategy_registry import REGISTRY_VERSION, list_strategies
from services import paper_research_policy as research
from services.paper_admission_policy import capture, fingerprint
from services.strategy_driven_paper_service import StrategyDrivenPaperService
from services.strategy_paper_automation import StrategyPaperAutomation
from services.strategy_paper_reporting import StrategyPaperReporting
from tests.test_approved_horizon_strategies import pair
from tests.test_pc_paper_account_policy import book as book

pytestmark = pytest.mark.usefixtures("previous_horizon_scope")


@pytest.fixture
def forward(book):
    book.auto.allowed_signals = ("STRONG BUY", "BUY")
    key, context, _, row = pair(12)
    row["FIB_DAY_R1"] = 150.0
    now = row.name.to_pydatetime() + timedelta(minutes=15)
    plan = rules.plan_for(key, row, context)
    validation = {
        "status": "completed",
        "registry_version": REGISTRY_VERSION,
        "run_id": "completed-research",
        "admission_policy_hash": fingerprint(capture(book.auto)),
        "request": {
            "universes": ["NIFTY 500"],
            "modes": ["intraday", "swing", "positional"],
            "source": "all",
        },
        "strategy_validation": [
            {
                "strategy_id": d["strategy_id"],
                "mode": mode,
                "registry_paper_eligible": d["paper_eligible"],
                "promotion_status": "NOT_ELIGIBLE",
                "universe_gates": [{"universe": "NIFTY 500", "status": "FAIL"}],
            }
            for d in list_strategies()
            if rules.active(d["strategy_id"])
            for mode in d["modes"]
        ],
    }
    candidate = {
        "symbol": "ABC",
        "bar_at": row.name.isoformat(),
        "consensus": "BUY",
        "consensus_score": 100,
        "strategy_evaluations": [
            {
                "strategy_id": key,
                "status": "evaluated",
                "signal": "BUY",
                "score": 100,
                "paper_eligible": True,
                "risk": plan,
            }
        ],
    }
    scan = {
        "status": "degraded",
        "run_id": "forward-scan",
        "universe": "NIFTY 500",
        "mode": "intraday",
        "requested_symbols": 501,
        "completed_symbols": 498,
        "error_symbols": 3,
        "top_picks": [candidate],
        "results": [candidate, *({"symbol": f"OK{i}"} for i in range(497))],
        "errors": [{"symbol": f"BAD{i}"} for i in range(3)],
    }
    policy = research.create(book.auto, validation, universe="NIFTY 500", now=now)
    scanner = SimpleNamespace(
        results=lambda: {"last_result": scan, "scanner_status": "completed"}
    )
    bridge = StrategyDrivenPaperService(
        scanner_service=scanner, paper_auto_entry=book.auto
    )
    return SimpleNamespace(
        book=book,
        key=key,
        now=now,
        validation=validation,
        scan=scan,
        policy=policy,
        bridge=bridge,
        scanner=scanner,
    )


def preview(env, *, research_mode=True):
    return env.bridge._prepare(
        strategy_id=env.key,
        scan_run_id=env.scan["run_id"],
        validation_run_id=env.validation["run_id"],
        validation_status=env.validation,
        now=env.now,
        research_policy=env.policy if research_mode else None,
    )[0]


def test_research_fill_uses_real_risk_cost_and_persistent_ledger(forward):
    env = forward
    before = deepcopy(env.validation)
    assert len(env.policy["strategy_pairs"]) == 10
    assert preview(env, research_mode=False)["status"] == "blocked"
    result = env.bridge.execute(
        strategy_id=env.key,
        scan_run_id=env.scan["run_id"],
        validation_run_id=env.validation["run_id"],
        validation_status=env.validation,
        research_policy=env.policy,
        now=env.now,
        admission_guard=lambda row: True,
    )
    assert result["paper_result"]["opened_count"] == 1, result
    saved = dict(env.book.repository.open_trades()[0])
    assert saved["admission_mode"] == "research"
    assert saved["research_policy_id"] == env.policy["policy_id"]
    position = env.book.paper.runtime.snapshot()["positions"][0]
    assert position["admission_mode"] == "research"
    assert (
        position["paper_plan"]["execution_economics"]["admission_policy_hash"]
        == env.policy["admission_policy_hash"]
    )
    assert env.validation == before
    assert result["safety"]["broker_orders_created"] == 0
    assert preview(env, research_mode=False)["status"] == "blocked"


@pytest.mark.parametrize(
    "change",
    [
        "coverage",
        "unaccounted",
        "failed_stock",
        "missing_bar",
        "missing_own_data",
        "policy_changed",
        "registry_changed",
        "source_changed",
        "wrong_strategy",
        "wrong_universe",
    ],
)
def test_research_does_not_bypass_data_scope_and_account_guards(forward, change):
    env = forward
    if change == "coverage":
        env.scan.update(completed_symbols=440, error_symbols=61)
    elif change == "unaccounted":
        env.scan["completed_symbols"] -= 1
    elif change == "failed_stock":
        env.scan["errors"].append({"symbol": "ABC"})
    elif change == "missing_bar":
        env.scan["top_picks"][0].pop("bar_at")
    elif change == "missing_own_data":
        env.scan["results"] = env.scan["results"][1:]
    elif change == "policy_changed":
        env.book.auto.minimum_rr += 1
    elif change == "registry_changed":
        env.policy["registry_version"] = "old"
    elif change == "source_changed":
        env.validation["run_id"] = "replacement"
    elif change == "wrong_strategy":
        env.key = rules.IDS[6]
    elif change == "wrong_universe":
        env.scan["universe"] = "NIFTY 100"
    result = preview(env)
    assert result["status"] in {"blocked", "no_candidates"}, result
    assert env.book.repository.open_trades() == []


def test_account_risk_rejection_still_blocks_research(forward):
    env = forward
    env.scan["top_picks"][0]["consensus_score"] = 10
    assert preview(env)["status"] == "risk_blocked"
    env.scan["top_picks"][0]["consensus_score"] = 100
    env.book.paper.environment_kill_switch = True
    assert preview(env)["status"] == "blocked"


def test_partial_exit_restore_and_reporting_retain_research_labels(forward):
    from services.paper_trading_runtime import PaperTradingRuntime

    env = forward
    env.bridge.execute(
        strategy_id=env.key,
        scan_run_id=env.scan["run_id"],
        validation_run_id=env.validation["run_id"],
        validation_status=env.validation,
        research_policy=env.policy,
        now=env.now,
    )
    runtime = env.book.paper.runtime
    trade = dict(env.book.repository.open_trades()[0])
    runtime.trades.partial_close(
        trade["id"],
        150.0,
        trade["quantity"] // 2,
        plan=runtime.portfolio.positions["ABC"].paper_plan,
        stoploss=trade["stoploss"],
        closed_at=env.now.isoformat(),
    )
    child = dict(runtime.trades.closed_trades()[0])
    assert child["admission_mode"] == "research"
    assert child["research_policy_id"] == env.policy["policy_id"]
    restored = PaperTradingRuntime(trades=env.book.repository)
    assert restored.restore_open() == 1
    assert restored.snapshot()["positions"][0]["admission_mode"] == "research"
    report = StrategyPaperReporting(SimpleNamespace(runtime=restored)).statement(
        now=env.now
    )
    row = next(row for row in report["rows"] if row["strategy_id"] == env.key)
    assert row["research_closed_count"] == row["research_open_count"] == 1


def test_research_start_stop_and_changed_policy_fail_closed(forward):
    from tests.test_saved_strategy_automation import Repository

    env = forward
    env.book.paper.health = lambda: {
        "enabled": True,
        "kill_switch": False,
        "can_open_new_positions": True,
        "entry_storage_policy": {
            "entry_allowed": True,
            "mode": "durable",
            "verified_persistent": True,
        },
    }
    service = StrategyPaperAutomation(
        scanner=env.scanner,
        bridge=env.bridge,
        repository=Repository(),
        quote_provider=SimpleNamespace(max_age_seconds=30),
        paper_monitor=SimpleNamespace(),
        strategy_monitor=SimpleNamespace(),
        validation_getter=lambda: env.validation,
        validation_starter=lambda **kwargs: pytest.fail(
            "Must reuse completed research"
        ),
        clock=lambda: env.now,
    )
    assert service.configure(True, admission_mode="research")["enabled"] is True
    candidate = {
        "symbol": "ABC",
        "strategy_id": env.key,
        "technical_mode": "intraday",
        "admission_mode": "research",
        "research_policy_id": service._research_policy["policy_id"],
        "entry_bar_at": env.scan["top_picks"][0]["bar_at"],
        "automation_quote_at": env.now.isoformat(),
    }
    assert service._admit(service._generation, candidate)
    stale = {
        **candidate,
        "automation_quote_at": (env.now - timedelta(minutes=5)).isoformat(),
    }
    assert not service._admit(service._generation, stale)
    env.book.auto.minimum_rr += 1
    assert not service._admit(service._generation, candidate)
    assert service.tick()["blockers"] == ["research_policy_no_longer_current"]
    service.configure(False)
    assert not service._admit(service._generation, candidate)


@pytest.mark.parametrize(
    "blocked_check", [None, "kill_switch_off", "storage_verified", "fresh_market_quote"]
)
def test_one_use_research_start_preserves_fail_results_and_limits(
    forward, monkeypatch, blocked_check
):
    from database.repositories.strategy_runtime_state_repository import (
        StrategyRuntimeStateRepository,
    )
    from services.paper_operator_request import (
        BASE_CHECKS,
        DEFERRED,
        run_paper_operator_request,
    )

    env = forward
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("TRENDFORGE_CLOUD_PAPER_EXECUTION", "true")
    repo = StrategyRuntimeStateRepository(db=env.book.db)
    env.book.paper.health = lambda: {
        "enabled": True,
        "kill_switch": False,
        "can_open_new_positions": True,
        "entry_storage_policy": {
            "entry_allowed": True,
            "mode": "durable",
            "verified_persistent": True,
        },
    }
    service = StrategyPaperAutomation(
        scanner=env.scanner,
        bridge=env.bridge,
        repository=repo,
        quote_provider=SimpleNamespace(max_age_seconds=30),
        paper_monitor=SimpleNamespace(),
        strategy_monitor=SimpleNamespace(),
        validation_getter=lambda: env.validation,
        validation_starter=lambda **kwargs: pytest.fail("No repeat historical run"),
        clock=lambda: env.now,
    )
    before = deepcopy(env.validation), capture(env.book.auto)
    command = json.dumps(
        {
            "id": "a" * 32,
            "action": "start_research_paper",
            "registry_version": REGISTRY_VERSION,
            "authorized_at": (env.now - timedelta(minutes=1)).isoformat(),
            "expires_at": (env.now + timedelta(minutes=2)).isoformat(),
            "confirm_render_executor": True,
        }
    )
    checks = dict.fromkeys(BASE_CHECKS | DEFERRED, True)
    checks["validated_strategy_pair_available"] = False
    if blocked_check:
        checks[blocked_check] = False

    async def sleep(seconds):
        env.now += timedelta(seconds=seconds)

    def readiness():
        return {
            "checks": checks,
            "eligible_strategy_pairs": 0,
            "automation_enabled": service.status()["enabled"],
        }

    kwargs = dict(
        automation_getter=lambda: service,
        validation_getter=lambda: env.validation,
        validation_starter=lambda request: pytest.fail("No repeat historical run"),
        readiness=readiness,
        clock=lambda: env.now,
        sleep=sleep,
    )
    asyncio.run(run_paper_operator_request(command, **kwargs))
    state = service.status()
    assert state["enabled"] is (blocked_check is None)
    if not blocked_check:
        assert (
            state["admission_mode"] == "research" and state["research_policy_current"]
        )
        receipt = repo.load_state("paper.operator:" + "a" * 32)["payload"]
        assert receipt["phase"] == "started_research"
        generation = state["control_generation"]
        asyncio.run(run_paper_operator_request(command, **kwargs))
        assert service.status()["control_generation"] == generation
    assert (env.validation, capture(env.book.auto)) == before
