"""Exact exported bytes and current-only selectors without a DownloadButton chunk."""

from io import BytesIO

import pytest

from scanner.strategy_horizons import HORIZONS, scanner_horizon_choices
from scanner.strategy_registry import get_strategy
from scanner.weekly_floor import STRATEGY_ID
from scanner.workspace_strategies import strategy_choices
from tests.support.native_downloads import DownloadParser, content, downloads
from tests.test_research_report_workspace import ReportClient, reports
from webapp.backtest_controls import backtest_choices
from webapp.downloads import download_html


@pytest.mark.parametrize(
    "value,mime,name",
    [
        ("symbol,entry\nEXAMPLE,123.45\n", "text/csv", "trades.csv"),
        (b"\xef\xbb\xbfsymbol,entry\r\nEXAMPLE,123.45\r\n", "text/csv", "trades.csv"),
        (
            BytesIO(b"PK\x03\x04binary-workbook"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "trades.xlsx",
        ),
        (
            b'{"batch_id":"old-batch","status":"completed"}',
            "application/json",
            "backup.json",
        ),
    ],
)
def test_native_link_preserves_exact_export_bytes(value, mime, name):
    parser = DownloadParser()
    parser.feed(download_html("Download", value, name, mime))
    link = parser.downloads[0]
    expected = (
        value.getvalue()
        if hasattr(value, "getvalue")
        else value.encode()
        if isinstance(value, str)
        else value
    )
    assert content(link) == expected
    assert link["download"] == name
    assert link["href"].startswith("data:" + mime + ";base64,")


def test_native_link_escapes_labels_and_filenames():
    html = download_html('<img src=x onerror="bad">', b"data", 'a"<x>.csv', "text/csv")
    assert "<img" not in html and 'download="a"' not in html
    parser = DownloadParser()
    parser.feed(html)
    assert parser.downloads[0]["label"] == '<img src=x onerror="bad">'
    assert parser.downloads[0]["download"] == 'a"<x>.csv'
    with pytest.raises(ValueError):
        download_html("Bad", b"data", "x.html", "text/html")


def test_archived_report_keeps_downloads_and_never_constructs_lazy_widget(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(
        st, "download_button", lambda *a, **k: pytest.fail("No lazy download widget")
    )
    client = ReportClient()
    app = reports(monkeypatch, client)
    links = downloads(app)
    assert [link["label"] for link in links] == [
        "Download CSV",
        "Download Excel (.xlsx)",
        "Download batch backup (.json)",
    ]
    assert content(links[0]) == client.batch["report"]["csv"].encode("utf-8-sig")
    assert len(app.dataframe) == 2


def test_every_selectable_scanner_is_the_new_weekly_strategy():
    by_mode = [strategy_choices(mode) for mode in ("intraday", "swing", "positional")]
    assert by_mode[:2] == [{}, {}]
    assert {value for choices in by_mode for value in choices.values()} == {STRATEGY_ID}
    by_horizon = {key: scanner_horizon_choices(key) for key in HORIZONS}
    assert all(not choices for key, choices in by_horizon.items() if key != "long_term")
    assert {r["strategy_id"] for r in by_horizon["long_term"].values()} == {STRATEGY_ID}
    assert {r["strategy_id"] for r in backtest_choices().values()} == {STRATEGY_ID}
    assert get_strategy("tf_ema100_200_bullish_pivot")[
        "strategy_id"
    ]  # Historical metadata retained.


@pytest.mark.parametrize("mode", ["intraday", "swing", "positional"])
def test_legacy_scanner_entry_routes_cannot_restore_retired_choices(mode, monkeypatch):
    from streamlit.testing.v1 import AppTest

    from tests.test_scanner_stock_backtests import Client
    from webapp import scanner_backtesting

    client = Client()
    monkeypatch.setattr(
        scanner_backtesting, "legacy_test_client", client, raising=False
    )
    app = AppTest.from_string(
        "from webapp.scanner_backtesting import (\n"
        "    render_scanner_backtests, legacy_test_client)\n"
        f"render_scanner_backtests(legacy_test_client, mode={mode!r}, authorized=True)"
    ).run(timeout=15)
    assert not app.exception
    assert app.selectbox[0].options == [get_strategy(STRATEGY_ID)["name"]]
    assert len(app.selectbox) == 3
    assert [button.label for button in app.button] == ["Scan stocks", "Backtest"]
