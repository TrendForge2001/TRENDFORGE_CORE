"""Full-universe scans and paper admission without larger portfolio risk."""

from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from api.admin_auth import require_admin_api_key
from api.app import MultiStrategyScanRequest, TechnicalScanRequest
from api.paper_automation_router import AutomationControl, paper_automation_router
from config.scanner_capacity import MAX_SCAN_SYMBOLS, QUOTE_BATCH_SIZE, SCAN_BATCH_SIZE
from providers.kite_paper_quotes import FreshKitePaperQuotes
from services.candle_batches import scan_candles
from services.multi_strategy_nifty_scanner import MultiStrategyNiftyScanner
from services.technical_trading_service import TechnicalTradingService
from tests.test_ema_pivot_scanners import IDS, signal_frame
from tests.test_multi_strategy_scanner_r72_5_2 import FakeUniverse, _daily_frame
from tests.test_saved_strategy_automation import build
from tests.test_staged_paper_execution import NOW, TZ, environment
from webapp.nifty_selection import scan_nifty_stocks


def test_api_limits_accept_full_universe_and_reject_oversize_before_work():
    symbols = [f"S{i:04d}" for i in range(MAX_SCAN_SYMBOLS)]
    assert len(TechnicalScanRequest(symbols=symbols, top_n=1000).symbols) == 1000
    assert MultiStrategyScanRequest(top_n=1000).top_n == 1000
    assert len(AutomationControl(enabled=True, symbols=symbols).symbols) == 1000
    for model, fields in (
        (TechnicalScanRequest, {}),
        (AutomationControl, {"enabled": True}),
    ):
        with pytest.raises(ValidationError):
            model(symbols=[*symbols, "EXCESS"], **fields)


def test_paper_start_and_restart_preserve_500_verified_targets():
    env = build(now=NOW)
    symbols = [f"S{i:03d}" for i in range(500)]
    env.service.scanner.universe_provider = SimpleNamespace(
        load=lambda universe: {"members": [{"symbol": s} for s in symbols]}
    )
    app = FastAPI()
    app.dependency_overrides[require_admin_api_key] = lambda: None
    app.include_router(
        paper_automation_router(
            automation_getter=lambda: env.service, paper_getter=lambda: None
        )
    )
    client = TestClient(app)
    response = client.put(
        "/paper/automation", json={"enabled": True, "symbols": symbols}
    )
    assert response.status_code == 200
    assert response.json()["target_symbols"] == symbols
    env.service.tick()
    assert all(call["top_n"] == MAX_SCAN_SYMBOLS for call in env.scans)
    restored = build(repo=env.repo, now=NOW).service.status()
    assert restored["target_symbols"] == symbols and restored["enabled"] is False
    assert restored["max_target_symbols"] == MAX_SCAN_SYMBOLS
    client.put("/paper/automation", json={"enabled": False})
    assert (
        client.put(
            "/paper/automation",
            json={"enabled": True, "symbols": [*symbols, "OUTSIDE"]},
        ).status_code
        == 422
    )


def test_history_batches_release_each_chunk_and_preserve_provider_owned_mapping():
    symbols = [f"S{i}" for i in range(501)]
    owned = {s: object() for s in symbols}
    batches, progress = [], []

    def fetch(chunk, **kwargs):
        assert len(chunk) <= SCAN_BATCH_SIZE
        batches.append(chunk)
        return {s: owned[s] for s in chunk if s != "S37"}, {"S37": "unavailable"}

    rows = list(
        scan_candles(
            SimpleNamespace(batch_candles_with_errors=fetch),
            symbols,
            period="2y",
            interval="1d",
            progress=lambda n, total: progress.append((n, total)),
        )
    )
    assert [row[0] for row in rows] == symbols
    assert rows[37][1:] == (None, "unavailable")
    assert sum(len(chunk) for chunk in batches) == 501
    assert progress[-1] == (500, 501)
    shared = {"TCS": _daily_frame()}
    list(
        scan_candles(
            SimpleNamespace(batch_candles_with_errors=lambda *a, **k: (shared, {})),
            ["TCS"],
            period="2y",
            interval="1d",
        )
    )
    assert "TCS" in shared


def test_direct_technical_scan_scores_501_stocks_in_bounded_batches(monkeypatch):
    symbols = [f"S{i:03d}" for i in range(501)]
    frame = _daily_frame()
    chunks = []

    def fetch(chunk, **kwargs):
        chunks.append(list(chunk))
        return dict.fromkeys(chunk, frame), {}

    signal = {
        "signal": "BUY",
        "score": 100,
        "confidence": 90,
        "trigger": "fixture",
        "risk": {"entry": 100, "stoploss": 95, "target2": 110, "reward_risk": 2},
        "evidence": [],
        "indicators": {},
    }
    monkeypatch.setattr(
        "services.technical_trading_service.workspace_signal", lambda *a, **k: signal
    )
    service = TechnicalTradingService(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        indicator_engine=SimpleNamespace(calculate=lambda df: df),
        repository=SimpleNamespace(),
    )
    result = service.scan(
        symbols=symbols,
        mode="swing",
        strategy_id="tf_swing_ema20_50_rsi_volume",
        top_n=MAX_SCAN_SYMBOLS,
        now=NOW,
    )
    assert result["requested_symbols"] == result["completed_symbols"] == 501
    assert {row["symbol"] for row in result["results"]} == set(symbols)
    assert max(map(len, chunks)) == SCAN_BATCH_SIZE and len(chunks) == 21
    assert result["safety"]["paper_execution_requested"] is False


def test_500_stock_scan_can_fill_signals_beyond_first_100_with_three_shared_slots(
    tmp_path, monkeypatch
):
    env = environment(tmp_path, monkeypatch)
    pair = signal_frame(env.key, mode="intraday")
    stamps = [
        stamp
        for day in pd.bdate_range("2026-10-19", "2026-10-30")
        for stamp in pd.date_range(
            day.strftime("%Y-%m-%d") + " 09:15", periods=25, freq="15min", tz=TZ
        )
    ] + list(pd.date_range("2026-11-02 09:15", periods=4, freq="15min", tz=TZ))
    frame = pd.concat(
        [pair.iloc[:1]] * (len(stamps) - 1) + [pair.iloc[-1:]], ignore_index=True
    )
    frame.index = pd.DatetimeIndex(stamps)
    chunks, progress = [], []

    def fetch(chunk, **kwargs):
        chunks.append(list(chunk))
        return dict.fromkeys(chunk, frame), {}

    monkeypatch.setenv(
        "TRENDFORGE_MULTI_STRATEGY_RESULTS_PATH", str(tmp_path / "scan.json")
    )
    scanner = MultiStrategyNiftyScanner(
        market_data=SimpleNamespace(batch_candles_with_errors=fetch),
        indicator_engine=SimpleNamespace(calculate=lambda df: df),
        universe_provider=FakeUniverse(),
    )
    original_progress = scanner._record_progress

    def record(**kwargs):
        original_progress(**kwargs)
        progress.append(scanner.status()["progress"])

    monkeypatch.setattr(scanner, "_record_progress", record)
    symbols = [f"S{i:03d}" for i in range(500)]
    scan = scanner.scan(
        universe="NIFTY 500",
        mode="intraday",
        target_symbols=symbols,
        strategy_ids=[env.key],
        top_n=MAX_SCAN_SYMBOLS,
        now=NOW,
    )
    assert scan["status"] == "completed" and scan["completed_symbols"] == 500
    assert len(scan["top_picks"]) == 500
    assert len(chunks) == 20 and max(map(len, chunks)) == SCAN_BATCH_SIZE
    assert any(
        p["phase"] == "fetching_kite_candles" and p["processed_symbols"] == 475
        for p in progress
    )
    assert progress[-1]["processed_symbols"] == 500
    env.executor.cancel()
    env.executor.arm(
        scan, env.validation, [env.key], short_borrow_assumed=False, now=NOW
    )
    assert len(env.executor.pending) == 500
    tradable = set(symbols[-3:])
    env.quotes.broker.quote = lambda instruments: {
        instrument: {
            "last_price": 103.1 if instrument[4:] in tradable else 100,
            "timestamp": NOW,
        }
        for instrument in instruments
    }
    result = env.executor.process(
        now=NOW, validation=env.validation, admission_guard=lambda c: True
    )
    assert result["opened_count"] == 3
    assert set(env.runtime.portfolio.positions) == tradable
    positions = env.runtime.snapshot()["positions"]
    assert sum(row["quantity"] * row["average_price"] for row in positions) <= 80000
    assert env.runtime.trades.count() == 3
    assert (
        env.executor.process(
            now=NOW, validation=env.validation, admission_guard=lambda c: True
        )["opened_count"]
        == 0
    )


def test_1000_quote_targets_are_batched_and_stale_tail_still_fails_closed(monkeypatch):
    calls, sleeps = [], []
    stale = False
    instruments = [f"NSE:S{i:04d}" for i in range(1000)]

    def quote(chunk):
        calls.append(list(chunk))
        assert len(chunk) <= QUOTE_BATCH_SIZE
        return {
            s: {
                "last_price": 100,
                "timestamp": NOW
                - timedelta(seconds=61 if stale and s == instruments[-1] else 0),
            }
            for s in chunk
        }

    monkeypatch.setattr("providers.kite_paper_quotes.time.sleep", sleeps.append)
    quotes = FreshKitePaperQuotes(SimpleNamespace(quote=quote))
    assert len(quotes.prices(instruments, now=NOW)) == 1000
    assert list(map(len, calls)) == [500, 500] and len(sleeps) == 1
    stale = True
    with pytest.raises(ValueError, match="stale"):
        quotes.prices(instruments, now=NOW)


def test_scanner_handoff_can_start_all_500_stocks(monkeypatch):
    import webapp.paper_handoff as handoff

    monkeypatch.setattr(handoff, "admin_key_configured", lambda: True)
    calls = []
    client = SimpleNamespace(
        get_json=lambda *a: {"enabled": False, "worker_running": True, "blockers": []},
        put_json=lambda path, body: calls.append((path, body)),
    )
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from webapp.paper_handoff import render_scanner_paper_handoff\n"
        "render_scanner_paper_handoff(st.session_state.client, "
        "st.session_state.snapshot)"
    )
    app.session_state["client"] = client
    symbols = [f"S{i:03d}" for i in range(500)]
    app.session_state["snapshot"] = {
        "strategy_id": IDS[0],
        "results": [{"symbol": s, "signal": "BUY"} for s in symbols],
    }
    app.run(timeout=15)
    assert not app.exception and app.multiselect[0].value == symbols
    next(b for b in app.button if b.key == "scanner_paper_start").click().run(
        timeout=15
    )
    assert not app.exception
    assert calls[0][1]["symbols"] == symbols
    assert calls[0][1]["enabled"] is True


def test_frontend_progress_accounts_for_every_stock():
    from tests.test_nifty_workspace_selection import ScanClient

    progress = []
    result = scan_nifty_stocks(
        ScanClient(),
        {"symbols": [f"S{i}" for i in range(501)]},
        mode="swing",
        period="2y",
        strategy_id=None,
        progress=lambda done, total: progress.append((done, total)),
    )
    assert progress[0] == (0, 501) and progress[-1] == (501, 501)
    assert result["completed_symbols"] == 501
