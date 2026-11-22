"""Paused horizons reject new work while stored positions remain monitorable."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app import create_app
from api.research_reports_router import research_reports_router
from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from core.database import initialize_database
from database.repositories.backtest_results import BacktestResultsRepository
from database.repositories.trade_repository import TradeRepository
from scanner import approved_strategies as rules
from scanner.multi_strategy_engine import MultiStrategyEngine
from scanner.strategy_horizons import (
    HORIZONS,
    horizon_strategy,
    scanner_horizon_choices,
)
from scanner.strategy_registry import get_strategy, list_strategies, registry_readiness
from services.approved_paper_plan import advance, validate
from services.paper_trading_runtime import PaperTradingRuntime
from services.research_batches import ResearchBatchManager
from tests.test_approved_horizon_strategies import pair


def test_current_validation_scope_drops_paused_modes_and_rejects_intraday_only():
    from scanner.strategy_scope import active_modes, effective_modes

    assert active_modes() == ("swing", "positional")
    assert effective_modes(["intraday", "swing", "positional"]) == [
        "swing",
        "positional",
    ]
    with pytest.raises(ValueError, match="active"):
        effective_modes(["intraday"])


def test_old_automatic_scanner_never_schedules_or_fetches_paused_intraday():
    from datetime import UTC, datetime

    from services.technical_auto_scanner import TechnicalAutoScanner

    scanner = object.__new__(TechnicalAutoScanner)
    assert scanner._intraday_slot(datetime.now(UTC)) is None
    with pytest.raises(ValueError, match="paused"):
        scanner.run_once("intraday")


@pytest.mark.parametrize("kind", ["scan", "backtest"])
@pytest.mark.parametrize("explicit", [False, True])
def test_legacy_technical_routes_reject_paused_work_before_service_execution(
    kind, explicit
):
    class Service:
        def scan(self, **kwargs):
            pytest.fail("Paused scans must never execute")

        backtest = scan

    client = TestClient(create_app(SimpleNamespace(technical_trading_service=Service)))
    request = {"mode": "intraday"}
    request.update(
        {"symbols": ["EXAMPLE"]} if kind == "scan" else {"symbol": "EXAMPLE"}
    )
    if explicit:
        request["strategy_id"] = rules.IDS[0]
    response = client.post("/technical/" + kind, json=request)
    assert response.status_code == 422
    assert "paused" in response.json()["detail"]


def test_current_catalog_has_only_short_and_long_scanners_and_no_short_entries():
    assert set(HORIZONS) == {"short_term", "medium_term", "long_term"}
    assert len(list_strategies()) == 9
    assert not list_strategies(mode="intraday")
    assert len(scanner_horizon_choices("short_term")) == 4
    assert len(scanner_horizon_choices("long_term")) == 5
    assert not scanner_horizon_choices("medium_term")
    assert registry_readiness()["intraday_short_strategies"] == 0
    for row in list_strategies():
        assert row["direction"] == "LONG"
        for mode in row["modes"]:
            if row["strategy_id"] in rules.APPROVED_IDS and not rules.exit_only(
                row["strategy_id"], mode
            ):
                assert rules.direction(row["strategy_id"], mode) == 1


@pytest.mark.parametrize(
    "n,mode,horizon",
    [
        (15, "swing", "short_term"),
        (17, "positional", "long_term"),
        (19, "positional", "long_term"),
    ],
)
def test_bearish_choices_are_removed_and_direct_new_runs_are_blocked(n, mode, horizon):
    from scanner.strategy_scope import require_entry_scope
    from scanner.workspace_strategies import validate_workspace_strategy

    key = rules.IDS[n - 1]
    definition = get_strategy(key)
    assert definition["implementation_status"] == "suspended_bearish"
    assert definition["paper_eligible"] is False
    assert key in registry_readiness()["paused_strategy_ids"]
    with pytest.raises(ValueError, match="Bearish"):
        require_entry_scope(key, mode=mode, horizon=horizon)
    with pytest.raises(ValueError, match="Bearish"):
        validate_workspace_strategy(mode, key)
    with pytest.raises(ValueError):
        MultiStrategyEngine().strategies(mode=mode, strategy_ids=[key])
    with pytest.raises(ValueError):
        MultiStrategyBacktestEngine().validate_strategy(key, mode=mode)
    with pytest.raises(ValueError):
        horizon_strategy(horizon, key)


@pytest.mark.parametrize("n,mode", [(15, "swing"), (17, "swing"), (19, "positional")])
def test_removed_bearish_ids_keep_existing_position_exit_lineage(n, mode):
    from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
    from tests.test_ema_pivot_scanners import signal_frame

    key = rules.IDS[n - 1]
    frame = signal_frame(key, mode=mode)
    engine = MultiStrategyEngine()
    held = engine.evaluate_exit(frame, mode=mode, interval="1d", strategy_ids=[key])[
        "evaluations"
    ][0]
    assert held["signal"] == "HOLD"
    assert held["exit_only"] is True and held["paper_eligible"] is False
    fast = EMA_PIVOT_SETUPS[key].fast
    frame.loc[frame.index[-1], "close"] = frame.iloc[-1][f"EMA_{fast}"] + 1
    exited = engine.evaluate_exit(frame, mode=mode, interval="1d", strategy_ids=[key])[
        "evaluations"
    ][0]
    assert exited["signal"] == "EXIT"
    assert exited["exit_only"] is True and exited["paper_eligible"] is False


@pytest.mark.parametrize("horizon", ["intraday", "short_swing"])
def test_paused_horizons_are_not_an_alias_to_an_active_choice(horizon):
    with pytest.raises(ValueError):
        scanner_horizon_choices(horizon)
    with pytest.raises(ValueError):
        horizon_strategy(horizon, rules.IDS[2])


@pytest.mark.parametrize(
    "key", [rules.IDS[n - 1] for n in (1, 2, 7, 8, 9, 10, 11, 12, 13)]
)
def test_all_nine_paused_strategies_reject_new_engine_and_backtest_admission(key):
    definition = get_strategy(key)
    assert definition["implementation_status"] == "suspended_horizon"
    assert definition["paper_eligible"] is False
    with pytest.raises(ValueError):
        MultiStrategyEngine().strategies(mode="intraday", strategy_ids=[key])
    with pytest.raises(ValueError):
        MultiStrategyBacktestEngine().validate_strategy(key, mode="intraday")


@pytest.mark.parametrize(
    "n,horizon,mode", [(1, "intraday", "intraday"), (3, "short_swing", "swing")]
)
def test_old_plans_restore_and_advance_but_cannot_open_another_position(
    n, horizon, mode, tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "paper.db"))
    initialize_database()
    key, _, previous, row = pair(n)
    context = rules.context_for(key, mode, horizon=horizon)
    plan = rules.plan_for(key, row, context)
    kwargs = dict(
        entry=plan["entry"],
        stop=plan["stoploss"],
        target=plan.get("target2") or 0.0,
        mode=mode,
    )
    assert validate(key, plan, restoring=True, **kwargs)
    with pytest.raises(ValueError, match="paused"):
        validate(key, plan, **kwargs)
    repo = TradeRepository()
    repo.save(
        "EXAMPLE",
        "BUY",
        4,
        plan["entry"],
        stoploss=plan["stoploss"],
        target=plan.get("target2") or 0.0,
        created_at=previous.name.isoformat(),
        trade_mode=mode,
        strategy_id=key,
        paper_plan=plan,
    )
    runtime = PaperTradingRuntime(trades=repo)
    try:
        assert runtime.restore_open() == 1
        advance(runtime, "EXAMPLE", previous, row)
        assert runtime.portfolio.positions["EXAMPLE"].paper_plan["last_candle_at"]
    finally:
        runtime.close()


@pytest.mark.parametrize("kind", ["scan", "backtest"])
@pytest.mark.parametrize(
    "horizon,key",
    [
        ("intraday", rules.IDS[0]),
        ("short_swing", rules.IDS[2]),
        ("short_term", rules.IDS[14]),
        ("long_term", rules.IDS[16]),
        ("long_term", rules.IDS[18]),
    ],
)
def test_public_research_routes_reject_paused_choices_before_fetching_data(
    kind, horizon, key, tmp_path, monkeypatch
):
    token = "scope-admin-synthetic-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", token)
    path = str(tmp_path / "reports.db")
    initialize_database(path)
    technical = SimpleNamespace(repository=BacktestResultsRepository(db_path=path))
    app = FastAPI()
    app.include_router(
        research_reports_router(
            app,
            lambda: technical,
            manager_factory=lambda t: ResearchBatchManager(
                t, isolated=False, import_history=False
            ),
        )
    )
    try:
        with TestClient(app) as client:
            r = client.post(
                "/reports/" + kind,
                headers={"X-TrendForge-Admin-Key": token},
                json={
                    "symbols": ["EXAMPLE"],
                    "strategy_id": key,
                    "horizon": horizon,
                    "stock_list": "NIFTY 500",
                },
            )
            assert r.status_code == 422, r.text
            assert (
                client.get(
                    "/reports/batches", headers={"X-TrendForge-Admin-Key": token}
                ).json()["batches"]
                == []
            )
    finally:
        if hasattr(app.state, "research_batches"):
            app.state.research_batches.close(wait=True)
        technical.repository.close()
