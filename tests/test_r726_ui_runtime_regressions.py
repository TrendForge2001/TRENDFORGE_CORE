"""R72.6 widget interactions use matching API contracts without real orders."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from webapp.api_client import ApiError

ROOT = Path(__file__).resolve().parents[1]


def scan_result():
    return {
        "status": "completed",
        "requested_symbols": 1,
        "completed_symbols": 1,
        "error_symbols": 0,
        "buy_candidates": 0,
        "results": [{"symbol": "TCS", "signal": "HOLD", "score": 0}],
    }


def backtest_result():
    return {
        "status": "completed",
        "metrics": {"total_trades": 1, "profit_factor": 0.0},
        "trades": [],
    }


class Client:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.malformed = False

    def get_json(self, path, **kwargs):
        return {"data_policy": "kite_only", "profiles": {}}

    def post_json(self, path, payload, **kwargs):
        self.calls.append((path, payload))
        if self.fail:
            raise ApiError("Controlled provider failure", status_code=503)
        if self.malformed:
            return {
                "status": "completed",
                "metrics": ["invalid"],
                "results": ["invalid"],
            }
        return backtest_result() if path.endswith("backtest") else scan_result()


def page(monkeypatch, name, client):
    monkeypatch.setattr("webapp.runtime.api_client", lambda **kwargs: client)
    monkeypatch.setattr("webapp.runtime.admin_key_configured", lambda: True)
    result = AppTest.from_file(ROOT / "webapp/pages" / name).run(timeout=15)
    assert not result.exception
    return result


def button(app, label):
    return next(widget for widget in app.button if widget.label == label)


def test_scanner_mode_updates_history_before_first_submission(monkeypatch):
    client = Client()
    app = page(monkeypatch, "technical_scanner.py", client)
    app.radio[0].set_value("swing").run(timeout=15)
    assert app.selectbox[0].options == ["1y", "2y", "5y"]
    button(app, "Run technical scan").click().run(timeout=15)
    assert not app.exception
    path, request = client.calls[-1]
    assert path == "/technical/scan"
    assert request["mode"] == "swing"
    assert request["period"] == "2y"
    assert request["execute_paper"] is False


def test_backtest_mode_updates_history_and_displays_zero_profit_factor(monkeypatch):
    client = Client()
    app = page(monkeypatch, "kite_backtesting.py", client)
    app.radio[0].set_value("intraday").run(timeout=15)
    assert app.selectbox[0].options == ["30d", "45d", "60d"]
    button(app, "Run Kite backtest").click().run(timeout=15)
    assert not app.exception
    path, request = client.calls[-1]
    assert path == "/technical/backtest"
    assert request["mode"] == "intraday"
    assert request["period"] == "60d"
    assert (
        next(metric for metric in app.metric if metric.label == "Profit factor").value
        == "0.0"
    )


@pytest.mark.parametrize(
    "name,key,label,metric",
    [
        (
            "technical_scanner.py",
            "tf_r726_scan_result",
            "Run technical scan",
            "Processed",
        ),
        (
            "kite_backtesting.py",
            "tf_r726_backtest_result",
            "Run Kite backtest",
            "Profit factor",
        ),
    ],
)
@pytest.mark.parametrize("failure", ["transport", "malformed"])
def test_failed_new_request_clears_previous_result_instead_of_showing_stale_success(
    monkeypatch, name, key, label, metric, failure
):
    client = Client()
    app = page(monkeypatch, name, client)
    button(app, label).click().run(timeout=15)
    assert any(item.label == metric for item in app.metric)
    if failure == "transport":
        client.fail = True
    else:
        client.malformed = True
    button(app, label).click().run(timeout=15)
    assert not app.exception
    assert not any(item.label == metric for item in app.metric)
    with pytest.raises(KeyError):
        app.session_state[key]
    assert app.error


def daily_statement():
    return {
        "scope": "paper_trading_closed_trades",
        "period": "daily",
        "period_end": "2026-10-22T20:00:00Z",
        "summary": {
            "trade_count": 0,
            "gross_profit": 0,
            "gross_loss": 0,
            "net_pnl": 0,
        },
        "daily": [],
        "trades": [],
    }


def test_paper_page_qualifies_stale_marks_and_keeps_safety_controls_available(
    monkeypatch,
):
    calls = []
    statement = daily_statement()

    class PaperClient:
        def get_json(self, path, **kwargs):
            if path == "/workspace/paper-portfolio":
                return {
                    "portfolio": {
                        "open_positions": 0,
                        "positions": [],
                        "unrealized_pnl": 0,
                        "realized_pnl": 0,
                    }
                }
            if path == "/paper/readiness":
                return {
                    "can_open_new_positions": False,
                    "automatic_monitor": {"enabled": False, "running": False},
                }
            if path in {"/paper/automation", "/paper/strategy-pnl"}:
                raise ApiError("Controlled automation unavailable", status_code=503)
            if path == "/pnl":
                return statement
            raise AssertionError(path)

        def post_json(self, path, payload, **kwargs):
            calls.append(path)
            return {"status": "monitored"}

    app = page(monkeypatch, "paper_session.py", PaperClient())
    assert button(app, "Open paper position").disabled
    assert any(
        "Automatic quote monitoring is disabled" in item.value for item in app.warning
    )
    assert any("last saved position marks" in item.value for item in app.caption)
    assert not button(app, "Activate paper kill switch").disabled
    assert not button(app, "Run paper quote/SL monitor").disabled
    button(app, "Run paper quote/SL monitor").click().run(timeout=15)
    assert not app.exception
    assert calls == ["/paper/monitor/tick"]

    statement["period"] = "weekly"
    app.run(timeout=15)
    assert not app.exception
    assert any(
        "daily paper P&L response is incomplete or invalid" in item.value
        for item in app.error
    )
    assert not any(item.label == "Today's realized P&L" for item in app.metric)


@pytest.mark.parametrize(
    "failure",
    ["/workspace/paper-portfolio", "/paper/readiness", "/pnl", "missing_portfolio"],
)
def test_paper_read_failures_preserve_emergency_controls_without_inventing_data(
    monkeypatch, failure
):
    calls = []
    reads = []

    class PaperClient:
        def get_json(self, path, **kwargs):
            reads.append(path)
            if path == failure:
                raise ApiError("Controlled snapshot failure", status_code=503)
            if path == "/workspace/paper-portfolio":
                if failure == "missing_portfolio":
                    return {"status": "ready"}
                return {
                    "portfolio": {
                        "open_positions": 1,
                        "positions": [{"symbol": "TCS", "quantity": 1}],
                        "unrealized_pnl": 25.0,
                        "realized_pnl": 50.0,
                    }
                }
            if path == "/paper/readiness":
                return {
                    "can_open_new_positions": True,
                    "kill_switch": False,
                    "entry_storage_policy": {
                        "mode": "durable",
                        "entry_allowed": True,
                        "production": True,
                        "verified_persistent": True,
                        "ephemeral_simulation": False,
                    },
                    "automatic_monitor": {"enabled": True, "running": True},
                }
            if path in {"/paper/automation", "/paper/strategy-pnl"}:
                raise ApiError("Controlled automation unavailable", status_code=503)
            if path == "/pnl":
                return daily_statement()
            raise AssertionError(path)

        def post_json(self, path, payload, **kwargs):
            calls.append((path, payload))
            return {"status": "ok"}

    app = page(monkeypatch, "paper_session.py", PaperClient())
    for label in (
        "Activate paper kill switch",
        "Release paper kill switch",
        "Run paper quote/SL monitor",
        "Run strategy exit check",
    ):
        assert not button(app, label).disabled
    assert button(app, "Open paper position").disabled is (failure != "/pnl")
    assert set(reads) == {
        "/workspace/paper-portfolio",
        "/paper/readiness",
        "/pnl",
        "/paper/automation",
        "/paper/strategy-pnl",
    }
    if failure in {"/workspace/paper-portfolio", "missing_portfolio"}:
        assert not any("No open paper positions" in item.value for item in app.info)
        assert not any(item.label == "Today's realized P&L" for item in app.metric)
        assert not app.get("download_button")
        assert (
            next(item for item in app.metric if item.label == "Open positions").value
            == "Unavailable"
        )
    elif failure == "/paper/readiness":
        assert (
            next(item for item in app.metric if item.label == "Kill switch").value
            == "Unavailable"
        )
    else:
        assert not app.get("download_button")
    button(app, "Activate paper kill switch").click().run(timeout=15)
    assert not app.exception
    assert calls == [("/paper/kill-switch", {"enabled": True})]


def test_watchlist_cache_is_partitioned_by_backend_url(monkeypatch):
    import streamlit as st

    st.cache_data.clear()
    backend = ["https://first.test"]
    calls = []

    class PublicClient:
        def __init__(self, base_url, **kwargs):
            self.base_url = base_url

        def get_json(self, path, **kwargs):
            calls.append((self.base_url, path))
            symbol = "TCS" if self.base_url == "https://first.test" else "SBIN"
            return {"rows": [{"symbol": symbol, "stock_name": symbol, "ltp": 100.0}]}

    monkeypatch.setattr("webapp.api_client.TrendForgeApi", PublicClient)
    monkeypatch.setattr("webapp.runtime.api_url", lambda: backend[0])
    try:
        first = AppTest.from_file(ROOT / "webapp/pages/watchlists.py").run(timeout=15)
        assert not first.exception
        assert first.selectbox[0].options == ["TCS — TCS"]
        backend[0] = "https://second.test"
        second = AppTest.from_file(ROOT / "webapp/pages/watchlists.py").run(timeout=15)
        assert not second.exception
        assert second.selectbox[0].options == ["SBIN — SBIN"]
        assert {base for base, _ in calls} == {
            "https://first.test",
            "https://second.test",
        }
        assert len(calls) == 4
    finally:
        st.cache_data.clear()
