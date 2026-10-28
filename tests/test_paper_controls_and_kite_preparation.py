"""Operator target admission, stop races and read-only Kite preparation."""

from copy import deepcopy
from datetime import timedelta
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest
from test_saved_strategy_automation import NOW, build

from api.app import create_app
from api.paper_automation_router import paper_automation_router
from services.kite_trading_readiness import kite_trading_readiness

STRATEGY = "tf_intraday_ema9_20_momentum"


def scoped():
    env = build()
    env.service.scanner.universe_provider = SimpleNamespace(
        load=lambda universe: {"members": [{"symbol": "TCS"}, {"symbol": "SBIN"}]}
    )
    env.validation["request"]["universes"] = ["NIFTY 500"]
    return env


def test_rescan_and_final_guard_enforce_selected_stock_and_strategy():
    env = scoped()
    env.service.configure(
        True, universe="NIFTY 500", symbols=[" tcs ", "TCS"], strategy_ids=[STRATEGY]
    )
    state = env.service.status()
    assert state["target_symbols"] == ["TCS"]
    assert state["target_strategy_ids"] == [STRATEGY]
    env.service.tick()
    assert len(env.scans) == 1
    assert env.scans[0]["target_symbols"] == ["TCS"]
    assert env.scans[0]["strategy_ids"] == [STRATEGY]
    assert env.scans[0]["universe"] == "NIFTY 500"
    assert [row["strategy_id"] for row in env.executions] == [STRATEGY]
    candidate = {
        "symbol": "TCS",
        "strategy_id": STRATEGY,
        "technical_mode": "intraday",
        "entry_bar_at": (NOW - timedelta(minutes=15)).isoformat(),
        "automation_quote_at": NOW.isoformat(),
    }
    generation = env.service._generation
    assert env.service._admit(generation, candidate)
    assert not env.service._admit(generation, {**candidate, "symbol": "SBIN"})
    assert not env.service._admit(
        generation, {**candidate, "strategy_id": "tf_intraday_vwma9_26_rsi_volume"}
    )
    env.service.configure(False)
    assert not env.service._admit(generation, candidate)


@pytest.mark.parametrize(
    "selection",
    [
        {"symbols": []},
        {"symbols": ["OUTSIDE"]},
        {"symbols": ["../TCS"]},
        {"strategy_ids": ["tf_medium_ema50_100"]},
        {"strategy_ids": ["tpl_supertrend_rsi"]},
        {"universe": "unknown"},
    ],
)
def test_invalid_scanner_scope_never_arms_entries(selection):
    env = scoped()
    with pytest.raises(ValueError):
        env.service.configure(True, **selection)
    assert env.service.status()["enabled"] is False


def test_restart_retains_target_for_review_without_resuming_entries():
    env = scoped()
    env.service.configure(
        True, universe="NIFTY 500", symbols=["TCS"], strategy_ids=[STRATEGY]
    )
    restarted = build(repo=env.repo)
    state = restarted.service.status()
    assert state["enabled"] is False
    assert state["resume_required"] is True
    assert state["universe"] == "NIFTY 500"
    assert state["target_symbols"] == ["TCS"]
    assert state["target_strategy_ids"] == [STRATEGY]


def test_stop_cancels_a_start_that_is_still_validating_membership():
    env = scoped()
    waiting, release = Event(), Event()

    def load(universe):
        waiting.set()
        assert release.wait(5)
        return {"members": [{"symbol": "TCS"}]}

    env.service.scanner.universe_provider.load = load
    failures = []

    def start():
        try:
            env.service.configure(
                True, universe="NIFTY 500", symbols=["TCS"], strategy_ids=[STRATEGY]
            )
        except ValueError:
            failures.append(True)

    worker = Thread(target=start)
    worker.start()
    assert waiting.wait(5)
    try:
        env.service.configure(False)
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert failures == [True]
    assert env.service.status()["enabled"] is False


def test_scoped_validation_requires_the_same_parent_universe_and_receives_its_request():
    env = scoped()
    env.validation["request"]["universes"] = ["NIFTY 100"]
    requests = []
    env.service.validation_starter = lambda **kwargs: requests.append(kwargs)
    env.service.configure(
        True, universe="NIFTY 500", symbols=["TCS"], strategy_ids=[STRATEGY]
    )
    assert env.service.tick()["status"] == "validating_strategies"
    assert requests == [{"universe": "NIFTY 500"}]
    assert env.scans == [] and env.executions == []


def test_paper_stop_works_without_membership_or_readiness_and_api_validates_scope(
    monkeypatch,
):
    key = "test-paper-control-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    env = scoped()
    app = FastAPI()
    app.include_router(
        paper_automation_router(
            automation_getter=lambda: env.service, paper_getter=lambda: None
        )
    )
    client = TestClient(app, headers={"X-TrendForge-Admin-Key": key})
    response = client.put(
        "/paper/automation",
        json={
            "enabled": True,
            "universe": "NIFTY 500",
            "symbols": ["TCS"],
            "strategy_ids": [STRATEGY],
        },
    )
    assert response.status_code == 200
    env.service.scanner.universe_provider.load = lambda *args: (_ for _ in ()).throw(
        RuntimeError("unavailable")
    )
    assert (
        client.put("/paper/automation", json={"enabled": False}).json()["enabled"]
        is False
    )
    assert (
        client.put(
            "/paper/automation",
            json={"enabled": True, "strategy_ids": ["tf_long_ema100_200"]},
        ).status_code
        == 422
    )


def test_readiness_only_reads_health_and_quotes_even_when_broker_write_flags_are_on(
    monkeypatch,
):
    monkeypatch.setenv("TRENDFORGE_LIVE_TRADING_ENABLED", "true")
    calls = []

    class Broker:
        live_trading_enabled = True

        def health(self):
            calls.append("health")
            return {"authenticated": True}

        def quote(self, instruments):
            calls.append("quote")
            return {
                instrument: {"last_price": 100.0, "timestamp": NOW}
                for instrument in instruments
            }

    report = kite_trading_readiness(Broker(), probe_quotes=True, now=NOW)
    assert calls == ["health", "quote"]
    assert report["quote_status"] == "fresh"
    assert report["broker_write_opt_in_configured"] is True
    assert report["broker_orders_allowed"] is False
    assert report["orders_submitted"] == 0
    assert any(row["status"] == "pending_implementation" for row in report["checks"])


def test_kite_preparation_sanitizes_errors_and_distinguishes_stale_quotes():
    class Broker:
        def health(self):
            return {"authenticated": True}

        def quote(self, instruments):
            raise RuntimeError("private transport content")

    report = kite_trading_readiness(Broker(), probe_quotes=True, now=NOW)
    assert report["authenticated"] is True
    assert report["quote_status"] == "unavailable_or_stale"
    assert "private" not in str(report)
    Broker.health = lambda self: (_ for _ in ()).throw(
        RuntimeError("private credentials")
    )
    report = kite_trading_readiness(Broker(), now=NOW)
    assert report["authenticated"] is False
    assert "private" not in str(report)


def test_kite_readiness_endpoint_requires_admin_key_in_production(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ENV", "production")
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "a" * 40)
    client = TestClient(create_app(SimpleNamespace()))
    assert client.get("/workspace/kite-trading-readiness").status_code == 401


def test_scanner_handoff_start_and_stop_buttons_change_only_paper_targets(monkeypatch):
    calls = []
    state = {"enabled": False, "phase": "off", "worker_running": True, "blockers": []}

    class Client:
        def get_json(self, *args, **kwargs):
            return deepcopy(state)

        def put_json(self, path, payload):
            calls.append((path, payload))
            state["enabled"] = payload["enabled"]
            return deepcopy(state)

    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    source = """
from webapp.runtime import api_client
from webapp.paper_handoff import render_scanner_paper_handoff
render_scanner_paper_handoff(api_client(), {
    "strategy_id": "tf_intraday_ema9_20_momentum", "results": [
    {"symbol": "TCS", "signal": "BUY"}, {"symbol": "SBIN", "signal": "HOLD"}]})
"""
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert app.multiselect[0].value == ["TCS"]
    next(
        w for w in app.button if w.label == "Start paper trading selected stocks"
    ).click().run(timeout=15)
    assert not app.exception
    assert calls[-1] == (
        "/paper/automation",
        {
            "enabled": True,
            "universe": "NIFTY 500",
            "symbols": ["TCS"],
            "strategy_ids": [STRATEGY],
        },
    )
    next(
        w for w in app.button if w.label == "Stop automated paper trading"
    ).click().run(timeout=15)
    assert not app.exception
    assert calls[-1] == ("/paper/automation", {"enabled": False})


def test_status_error_does_not_hide_the_stop_button(monkeypatch):
    from webapp.api_client import ApiError

    class Client:
        def get_json(self, *args, **kwargs):
            raise ApiError("Unavailable", status_code=503)

    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    source = """
from webapp.runtime import api_client
from webapp.paper_handoff import render_scanner_paper_handoff
render_scanner_paper_handoff(api_client(), {
    "strategy_id": "tf_intraday_ema9_20_momentum", "results": []})
"""
    app = AppTest.from_string(source).run(timeout=15)
    assert not app.exception
    assert not next(
        w for w in app.button if w.label == "Stop automated paper trading"
    ).disabled


def test_kite_preparation_button_remains_available_if_account_snapshot_fails(
    monkeypatch,
):
    from webapp.api_client import ApiError

    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            calls.append(path)
            if path == "/workspace/kite-session":
                raise ApiError("Account view unavailable", status_code=503)
            return {
                "checks": [{"check": "Session", "status": "blocked"}],
                "notes": "Read-only preparation",
            }

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    from pathlib import Path

    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/live_kite.py"
    ).run(timeout=15)
    assert not app.exception
    next(
        w for w in app.button if w.label == "Check Kite trading readiness"
    ).click().run(timeout=15)
    assert not app.exception
    assert "/workspace/kite-trading-readiness" in calls


def test_real_scanner_filters_verified_parent_members_before_fetching_candles(
    tmp_path, monkeypatch
):
    from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner

    monkeypatch.setenv(
        "TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "snapshot.json")
    )
    requested = []

    class Market:
        def batch_candles_with_errors(self, symbols, **kwargs):
            requested.append(symbols)
            return {}, {symbol: "Unavailable" for symbol in symbols}

    universe = SimpleNamespace(
        load=lambda *args, **kwargs: {
            "members": [{"symbol": "TCS"}, {"symbol": "SBIN"}],
            "count": 2,
        }
    )
    scanner = MultiStrategyNiftyScanner(
        market_data=Market(), universe_provider=universe
    )
    result = scanner.scan(
        universe="NIFTY 500",
        mode="intraday",
        strategy_ids=[STRATEGY],
        target_symbols=["TCS"],
        now=NOW,
    )
    assert requested == [["TCS"]]
    assert result["requested_symbols"] == 1
    with pytest.raises(ValueError):
        scanner.scan(
            universe="NIFTY 500",
            mode="intraday",
            strategy_ids=[STRATEGY],
            target_symbols=["OUTSIDE"],
            now=NOW,
        )
    assert requested == [["TCS"]]


def test_targets_cannot_be_replaced_while_paper_automation_is_running():
    env = scoped()
    env.service.configure(
        True, universe="NIFTY 500", symbols=["TCS"], strategy_ids=[STRATEGY]
    )
    with pytest.raises(ValueError, match="Stop paper automation"):
        env.service.configure(
            True, universe="NIFTY 500", symbols=["SBIN"], strategy_ids=[STRATEGY]
        )
    assert env.service.status()["target_symbols"] == ["TCS"]
    env.service.configure(False)
    env.service.configure(
        True, universe="NIFTY 500", symbols=["SBIN"], strategy_ids=[STRATEGY]
    )
    assert env.service.status()["target_symbols"] == ["SBIN"]


def test_paper_tab_upgrades_saved_universe_only_on_explicit_start(monkeypatch):
    state = {
        "enabled": False,
        "phase": "off",
        "worker_running": True,
        "blockers": [],
        "universe": "NIFTY 100",
        "target_symbols": ["TCS"],
        "target_strategy_ids": [STRATEGY],
        "strategies": [
            {
                "strategy_id": STRATEGY,
                "name": "Selected EMA strategy",
                "paper_eligible": True,
            },
            {
                "strategy_id": "other",
                "name": "Unselected strategy",
                "paper_eligible": True,
            },
        ],
    }
    calls = []

    class Client:
        def get_json(self, path, **kwargs):
            return deepcopy(state)

        def put_json(self, path, payload):
            calls.append((path, payload))
            state.update(enabled=payload["enabled"], universe=payload["universe"])

    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    app = AppTest.from_string(
        "from webapp.runtime import api_client\n"
        "from webapp.paper_automation import render_paper_automation\n"
        "render_paper_automation(api_client(), view='Open positions')\n"
    ).run(timeout=15)
    assert not app.exception
    assert calls == []
    assert any("saved paper universe is not NIFTY 500" in w.value for w in app.warning)
    captions = "\n".join(w.value for w in app.caption)
    assert "Selected strategies: Selected EMA strategy" in captions
    assert "Unselected strategy" not in captions
    next(
        w for w in app.button if w.label == "Start automated paper trading"
    ).click().run(timeout=15)
    assert not app.exception
    assert calls == [
        (
            "/paper/automation",
            {
                "enabled": True,
                "universe": "NIFTY 500",
                "symbols": ["TCS"],
                "strategy_ids": [STRATEGY],
            },
        )
    ]
