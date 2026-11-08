"""Horizon controls and separate backend-generated report rendering."""

from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from services.research_report import build_report
from tests.test_compact_backtesting import partial_result
from webapp.api_client import ApiError

ROOT = Path(__file__).resolve().parents[1]


def completed_batch():
    result = {
        **partial_result(),
        "run_id": "batch-1",
        "mode": "swing",
        "strategy_id": "tf_ema50_100_bullish_pivot",
    }
    return {
        "batch_id": "batch-1",
        "kind": "backtest",
        "horizon": "medium_term",
        "strategy_id": result["strategy_id"],
        "stock_list": "NIFTY 50",
        "created_at": "2026-11-08T01:00:00+00:00",
        "requested_symbols": 1,
        "completed_symbols": 1,
        "phase": "completed",
        "status": "completed",
        "report": build_report(
            result, kind="backtest", horizon="medium_term", stock_list="NIFTY 50"
        ),
    }


class ReportClient:
    def __init__(self):
        self.calls = []
        self.batch = completed_batch()

    def get_json(self, path, **kwargs):
        self.calls.append(path)
        if path == "/reports/batches":
            return {
                "batches": [
                    {key: value for key, value in self.batch.items() if key != "report"}
                ]
            }
        if path == "/reports/batches/batch-1":
            return deepcopy(self.batch)
        raise AssertionError(path)

    def post_json(self, *args, **kwargs):
        raise AssertionError("Opening reports cannot launch a new scan or backtest")


def reports(monkeypatch, client):
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(ROOT / "webapp/pages/reports.py").run(timeout=15)
    assert not app.exception
    return app


def test_completed_batch_displays_actual_exit_fills_and_backend_download(monkeypatch):
    client = ReportClient()
    app = reports(monkeypatch, client)
    assert not app.selectbox
    assert len(app.dataframe) == 2
    ledger = app.dataframe[1].value
    assert ledger["quantity"].tolist() == [5, 5]
    assert ledger["entry_price"].tolist() == [100, 100]
    assert ledger["exit_price"].tolist() == [110, 120]
    assert ledger["net_pnl"].sum() == 148
    assert len(app.get("download_button")) == 2
    assert [item.proto.label for item in app.get("download_button")] == [
        "Download CSV",
        "Download Excel (.xlsx)",
    ]
    app.run(timeout=15)
    assert not app.exception
    assert client.calls.count("/reports/batches/batch-1") == 1


@pytest.mark.parametrize("status", ["queued", "running", "failed", "interrupted"])
def test_incomplete_batch_does_not_show_trades_or_report_download(monkeypatch, status):
    client = ReportClient()
    client.batch.update(
        status=status,
        phase=status,
        completed_symbols=0,
        report=None,
        error_code="runtime_restarted",
    )
    app = reports(monkeypatch, client)
    assert len(app.dataframe) == 1 and not app.get("download_button")
    if status in {"queued", "running"}:
        assert app.info
    else:
        assert app.warning


def test_corrupt_completed_report_has_no_download_or_trade_rows(monkeypatch):
    client = ReportClient()
    client.batch["report"]["csv"] += "modified"
    app = reports(monkeypatch, client)
    assert app.error and len(app.dataframe) == 1
    assert not app.get("download_button")


def test_medium_and_long_term_strategy_are_daily_without_extra_dropdowns(monkeypatch):
    class Client:
        def get_json(self, path, **kwargs):
            return {"rows": [{"symbol": "TCS"}]}

    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: Client())
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    app = AppTest.from_file(ROOT / "webapp/pages/kite_backtesting.py").run(timeout=15)
    for label, ema in [("Medium Term", "50/100"), ("Long Term", "100/200")]:
        app.session_state["backtest_horizon"] = label
        app.run(timeout=15)
        assert not app.exception and len(app.selectbox) == 2
        assert app.selectbox[0].label == label + " strategy"
        assert all(ema in value for value in app.selectbox[0].options)
        assert any("1d candles" in item.value for item in app.caption)
        assert not app.radio and not app.checkbox and not app.multiselect


def test_core_api_badge_uses_liveness_without_broker_or_admin_key(monkeypatch):
    from webapp.core_status import core_status

    calls = []

    class Client:
        def __init__(self, endpoint, **kwargs):
            calls.append((endpoint, kwargs))

        def get_json(self, path, **kwargs):
            calls.append((path, kwargs))
            if path != "/livez":
                raise AssertionError("No broker calls")
            return {"service": "TrendForge Core", "status": "ok"}

    monkeypatch.setattr("webapp.core_status.TrendForgeApi", Client)
    core_status.clear()
    try:
        assert core_status("https://core.test") == ("Connected", "tf-dot-green")
        assert core_status("https://core.test") == ("Connected", "tf-dot-green")
        assert calls == [
            ("https://core.test", {"default_timeout": 2}),
            ("/livez", {"timeout": 2}),
        ]

        def failed(*args, **kwargs):
            raise ApiError("Controlled unavailable")

        monkeypatch.setattr(Client, "get_json", failed)
        core_status.clear()
        assert core_status("https://core.test")[0] == "Unavailable"
    finally:
        core_status.clear()
