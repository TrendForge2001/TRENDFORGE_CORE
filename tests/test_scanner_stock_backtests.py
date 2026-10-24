"""Multi-stock simulations preserve scanner provenance and isolate failed stocks."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from webapp.api_client import ApiError
from webapp.scanner_backtesting import (
    BATCH_KEY,
    comparison_rows,
    matching_rows,
    run_stock_batch,
    scanner_description,
)


def snapshot(mode="swing"):
    return {
        "status": "completed",
        "mode": mode,
        "period": "2y",
        "run_id": "scan-1",
        "results": [
            {"symbol": "TCS", "signal": "BUY", "score": 90},
            {"symbol": "SBIN", "signal": "BUY", "score": 80},
            {"symbol": "INFY", "signal": "ERROR", "score": 100},
            {"symbol": "ITC", "signal": "HOLD", "score": 50},
        ],
    }


class Client:
    def __init__(self):
        self.calls = []
        self.fail = set()
        self.malformed = False

    def get_json(self, path, **kwargs):
        return {}

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        if path == "/technical/scan":
            return snapshot(payload["mode"])
        if payload["symbol"] in self.fail:
            raise ApiError("sensitive provider text", status_code=503)
        return {
            "status": "completed",
            "symbol": payload["symbol"],
            "metrics": []
            if self.malformed
            else {"net_profit": -10, "profit_factor": 0.0},
            "trades": [{"net_pnl": -10}],
            "equity_curve": [],
        }


def test_filters_deduplicate_exclude_errors_and_do_not_mix_modes():
    scan = snapshot()
    scan["results"] += [
        scan["results"][0],
        {"symbol": "BAD", "signal": "BUY", "score": float("nan")},
    ]
    assert [r["symbol"] for r in matching_rows(scan, "swing", "BUY", 85)] == ["TCS"]
    assert len(matching_rows(scan, "swing", "All signals", 0)) == 3
    assert matching_rows(scan, "intraday", "BUY", 0) == []


def test_batch_uses_same_profile_and_preserves_failure_and_zero_metrics():
    client = Client()
    client.fail = {"SBIN"}
    progress = []
    batch = run_stock_batch(
        client,
        ["TCS", "SBIN", "TCS"],
        scan=snapshot(),
        settings={
            "capital": 100000,
            "period": "2y",
            "cost_bps": 12,
            "slippage_bps": 5,
        },
        progress=progress.append,
    )
    assert [path for path, _ in client.calls] == ["/technical/backtest"] * 2
    assert all(
        req["mode"] == "swing" and req["capital"] == 100000 for _, req in client.calls
    )
    assert len({req["run_id"] for _, req in client.calls}) == 2
    assert batch["scan_run_id"] == "scan-1"
    assert len(batch["selection"]) == 2
    rows = comparison_rows(batch)
    assert rows[0]["profit_factor"] == 0.0
    assert rows[0]["net_profit"] == -10
    assert rows[1]["status"] == "failed"
    assert "sensitive" not in str(batch)
    assert progress == [0.5, 1.0]


def test_malformed_result_is_failed_and_selection_is_bounded():
    client = Client()
    client.malformed = True
    batch = run_stock_batch(client, ["TCS"], scan=snapshot(), settings={})
    assert batch["results"] == []
    assert len(batch["errors"]) == 1
    for symbols in ([], [str(i) for i in range(101)]):
        with pytest.raises(ValueError):
            run_stock_batch(client, symbols, scan=snapshot(), settings={})


def test_description_matches_engine_profiles():
    assert "VWAP" in scanner_description("intraday")["indicators"]
    assert "EMA 20/50/100" in scanner_description("swing")["indicators"]
    assert scanner_description("intraday")["interval"] == "15m"


def button(app, label):
    return next(w for w in app.button if w.label == label)


def test_scanner_to_multistock_workflow_and_failure_replaces_previous_batch(
    monkeypatch,
):
    client = Client()
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/kite_backtesting.py"
    ).run(timeout=15)
    app.radio[1].set_value("Scanner matches").run(timeout=15)
    assert not app.exception
    assert button(app, "Backtest selected stocks").disabled
    button(app, "Scan stocks").click().run(timeout=15)
    assert not app.exception
    assert app.multiselect[0].value == ["TCS", "SBIN"]
    scan_request = client.calls[-1][1]
    assert scan_request["execute_paper"] is False
    button(app, "Backtest selected stocks").click().run(timeout=15)
    assert not app.exception
    assert len(app.session_state[BATCH_KEY]["results"]) == 2
    assert [
        req["symbol"] for path, req in client.calls if path.endswith("backtest")
    ] == ["TCS", "SBIN"]
    client.fail = {"TCS", "SBIN"}
    button(app, "Backtest selected stocks").click().run(timeout=15)
    assert not app.exception
    assert app.session_state[BATCH_KEY]["results"] == []
    assert len(app.session_state[BATCH_KEY]["errors"]) == 2
    app.radio[0].set_value("intraday").run(timeout=15)
    assert not app.exception
    assert button(app, "Backtest selected stocks").disabled


def test_saved_scanner_snapshot_reused_without_rescanning_and_admin_required(
    monkeypatch,
):
    client = Client()
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: False)
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "webapp/pages/kite_backtesting.py"
    ).run(timeout=15)
    app.session_state["tf_r726_scan_result"] = snapshot()
    app.radio[1].set_value("Scanner matches").run(timeout=15)
    assert not app.exception
    assert app.multiselect[0].value == ["TCS", "SBIN"]
    assert button(app, "Scan stocks").disabled
    assert button(app, "Backtest selected stocks").disabled
    assert client.calls == []


def test_non_snapshot_stock_and_error_symbol_are_not_tested():
    client = Client()
    for symbol in ["UNKNOWN", "INFY"]:
        with pytest.raises(ValueError):
            run_stock_batch(client, [symbol], scan=snapshot(), settings={})
    assert client.calls == []
