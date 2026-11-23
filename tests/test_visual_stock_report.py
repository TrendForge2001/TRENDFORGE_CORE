"""Source fidelity, approved-rule provenance and read-only report behavior."""

from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.stock_report_router import stock_report_router
from providers.company_report_provider import parse_company_page
from services.stock_report_service import StockReportService, news_rows
from webapp.stock_report_document import document

NOW = datetime(2026, 11, 22, 18, tzinfo=ZoneInfo("Asia/Kolkata"))
HTML = """<h1>Example &amp; Company</h1><ul id="top-ratios">
<li><span class="name">Market Cap</span>₹<span class="number">1,02,097</span>Cr.</li>
<li><span class="name">Stock P/E</span><span class="number">14.36</span></li>
<li><span class="name">Dividend Yield</span><span class="number">0</span>%</li></ul>
<section id="profit-loss">Figures in Rs. Crores<table>
<tr><th></th><th>Mar 2025</th><th>Mar 2026</th><th>Mar 2027</th><th>TTM</th></tr>

<tr><td>Sales +</td><td>100</td><td>120</td><td>130</td><td>125</td></tr>

<tr><td>Net Profit +</td><td>-5</td><td>0</td><td>20</td><td>10</td></tr>
</table></section>
<section id="shareholding"><table><tr><th></th><th>Sep 2026</th><th>Dec 2026</th></tr>

<tr><td>Promoters +</td><td>51.3%</td><td>51%</td></tr>
<tr><td>FIIs +</td><td>21%</td><td>22%</td></tr>

<tr><td>DIIs +</td><td>23.2%</td><td>23%</td></tr>
<tr><td>Public +</td><td>4.5%</td><td>4%</td></tr>
</table></section>"""


def company():
    return parse_company_page(
        HTML,
        symbol="EXAMPLE",
        url="https://www.screener.in/company/EXAMPLE/consolidated/",
        today=NOW.date(),
    )


def engine():
    calls = []
    dates = pd.bdate_range("2026-10-01", "2026-11-23", tz="Asia/Kolkata")
    frame = pd.DataFrame(
        {"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000.0},
        index=dates,
    )

    def scan(**kwargs):
        calls.append(kwargs)
        return {
            "results": [
                {
                    "symbol": kwargs["symbols"][0],
                    "signal": "WAIT",
                    "data_status": "READY",
                    "indicators": {"RSI_WILDER_14": 55},
                    "institutional_rating": {
                        "rating": "INSUFFICIENT_DATA",
                        "score": None,
                    },
                }
            ]
        }

    return SimpleNamespace(
        scan=scan, market_data=SimpleNamespace(candles=lambda *a, **k: frame)
    ), calls


def test_company_series_keep_losses_and_zero_and_reject_open_future_periods():
    facts = company()
    assert facts["metrics"]["dividend_yield_pct"] == 0
    assert facts["metrics"]["market_cap_cr"] == 102097
    assert [row["net_profit_cr"] for row in facts["annual"]] == [-5, 0]
    assert facts["shareholding"][0]["complete"]
    assert len(facts["shareholding"]) == 1
    assert "sector_pe" not in facts["metrics"]
    unverified = parse_company_page(
        HTML.replace("Figures in Rs. Crores", "Unknown units"),
        symbol="EXAMPLE",
        url="https://www.screener.in/",
        today=NOW.date(),
    )
    assert unverified["annual"] == []


def test_partial_shareholding_is_not_presented_as_complete():
    facts = parse_company_page(
        HTML.replace("<td>4.5%</td>", "<td>--</td>"),
        symbol="EXAMPLE",
        url="https://www.screener.in/",
        today=NOW.date(),
    )
    assert not facts["shareholding"][0]["complete"]
    assert facts["shareholding"][0]["total_percent"] == 95.5


def test_report_uses_approved_scan_without_execution_and_excludes_future_candles():
    technical, calls = engine()
    service = StockReportService(
        lambda: technical,
        company_provider=SimpleNamespace(get=lambda *a, **k: company()),
    )
    report = service.build("example", now=NOW)
    assert calls[0]["execute_paper"] is False
    assert calls[0]["strategy_id"] == "tf_swing_ema20_50_rsi_volume"
    assert report["price"]["bar_date"] == "2026-11-20"
    assert not report["trade_plan"]["reviewable_setup"]
    assert not report["broker_orders_allowed"]
    assert report["rating"]["score"] is None
    assert service.build("EXAMPLE", now=NOW) == report
    assert len(calls) == 1
    with pytest.raises(ValueError):
        service.build(
            "EXAMPLE",
            horizon="short_term",
            strategy_id="tf_intraday_ema9_20_momentum",
            now=NOW,
        )


def test_market_failure_keeps_company_sections_and_hides_provider_exception_body():
    def failed():
        raise RuntimeError("private credential from upstream")

    service = StockReportService(
        failed, company_provider=SimpleNamespace(get=lambda *a, **k: company())
    )
    report = service.build("EXAMPLE", now=NOW)
    assert report["price"]["value"] is None
    assert report["company"]["metrics"]["pe"] == 14.36
    assert "private credential" not in str(report)
    assert not report["trade_plan"]["reviewable_setup"]


def test_private_api_requires_auth_before_loading_any_source(monkeypatch):
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "stock-report-test-admin-key-" * 3)
    app = FastAPI()
    calls = []
    app.include_router(stock_report_router(lambda: calls.append("loaded")))
    client = TestClient(app)
    assert client.get("/reports/stocks/EXAMPLE").status_code == 401
    assert not calls
    response = client.get(
        "/reports/stocks/EXAMPLE?horizon=intraday",
        headers={"X-TrendForge-Admin-Key": "stock-report-test-admin-key-" * 3},
    )
    assert response.status_code == 422 and not calls


def test_news_requires_recent_dates_and_safe_links_and_export_escapes_markup():
    items = [
        {
            "title": "<script>alert(1)</script>",
            "link": "https://example.org/news",
            "published": "2026-11-20T12:00:00+05:30",
        },
        {
            "title": "Future",
            "link": "https://example.org/future",
            "published": "2026-12-01T00:00:00Z",
        },
        {
            "title": "Unsafe",
            "link": "javascript:alert(1)",
            "published": "2026-11-20T12:00:00Z",
        },
    ]
    rows = news_rows(items, NOW)
    assert len(rows) == 1
    technical, _ = engine()
    service = StockReportService(
        lambda: technical,
        company_provider=SimpleNamespace(get=lambda *a, **k: company()),
        news_getter=lambda: SimpleNamespace(news=lambda *a: items),
    )
    exported = document(service.build("EXAMPLE", now=NOW))
    assert "<script>" not in exported
    assert "&lt;script&gt;" in exported
    assert "UNRATED" in exported

    assert "1,02,097" in exported


def test_cache_changes_at_market_close_and_explicit_refresh_rechecks_technical_data():
    technical, calls = engine()
    service = StockReportService(
        lambda: technical,
        company_provider=SimpleNamespace(get=lambda *a, **k: company()),
    )
    before = NOW.replace(day=20, hour=15, minute=29)
    after = before.replace(minute=31)
    first = service.build("EXAMPLE", now=before)
    second = service.build("EXAMPLE", now=after)
    assert first["price"]["bar_date"] == "2026-11-19"
    assert second["price"]["bar_date"] == "2026-11-20"
    assert len(calls) == 2
    service.build("EXAMPLE", now=after)
    assert len(calls) == 2
    service.build("EXAMPLE", now=after, force_refresh=True)
    assert len(calls) == 3


def test_readable_rule_details_preserve_approved_short_and_long_exit_policies():
    from scanner.strategy_registry import get_strategy
    from services.stock_report_rules import readable_rules

    before = get_strategy("tf_swing_ema20_50_rsi_volume")
    short = readable_rules(before, "short_term")
    assert "two completed daily candles" in " ".join(short["stoploss_rules"])
    assert "15:00" not in str(short)
    assert "no fixed numeric" in " ".join(short["target_rules"])
    assert get_strategy("tf_swing_ema20_50_rsi_volume") == before
    long = readable_rules(get_strategy("tf_long_ema100_200"), "long_term")
    assert "50%" in " ".join(long["target_rules"])
    assert "Either complete rule group" in " ".join(long["stoploss_rules"])
    vwma = readable_rules(get_strategy("tf_swing_vwma9_26_rsi_volume"), "short_term")
    assert "RSI14 below 50 and volume above SMA20" in " ".join(vwma["stoploss_rules"])


def test_nested_yahoo_news_and_date_only_disclosures_keep_time_basis():
    rows = news_rows(
        [
            {
                "content": {
                    "title": "Sourced result",
                    "canonicalUrl": {"url": "https://example.org/result"},
                    "provider": {"displayName": "Example exchange"},
                    "pubDate": "2026-11-20T12:00:00Z",
                }
            },
            {
                "title": "Date only",
                "link": "https://example.org/date",
                "published": "2026-11-21",
            },
        ],
        NOW,
    )
    assert len(rows) == 2
    assert rows[0]["published_at"] is None
    assert rows[0]["time_basis"] == "SOURCE_DATE_ONLY"
    assert rows[1]["source"] == "Example exchange"


def test_authenticated_stock_report_read_does_not_enable_execution(monkeypatch):
    key = "visual-stock-report-admin-test-" * 3
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key)
    technical, calls = engine()
    app = FastAPI()
    app.include_router(
        stock_report_router(
            lambda: technical,
            company_provider=SimpleNamespace(get=lambda *a, **k: company()),
        )
    )
    client = TestClient(app)
    response = client.get(
        "/reports/stocks/EXAMPLE?refresh=true", headers={"X-TrendForge-Admin-Key": key}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "EXAMPLE"
    assert payload["broker_orders_allowed"] is False
    assert payload["technical"]["signal"] == "WAIT"
    assert payload["trade_plan"]["execution_enabled"] is False
    assert calls[0]["execute_paper"] is False


def test_saved_report_cannot_keep_paper_review_enabled_after_a_new_close():
    from webapp.stock_report_workspace import paper_review_allowed

    report = {
        "trade_plan": {"reviewable_setup": True},
        "price": {"bar_date": "2026-11-20"},
    }
    assert paper_review_allowed(report, now=NOW)
    assert not paper_review_allowed(report, now=NOW.replace(day=23, hour=16))


def test_real_report_scan_does_not_touch_paper_notifications(tmp_path):
    from core.database import initialize_database
    from tests.support.research_candles import technical_service

    target = str(tmp_path / "readonly.db")
    initialize_database(target)
    technical = technical_service(target)
    notifications = []
    technical.paper_auto_entry = SimpleNamespace(
        process_scan=lambda *a, **k: notifications.append(k)
    )
    technical.scan(
        symbols=["EXAMPLE"],
        mode="swing",
        strategy_id="tf_swing_ema20_50_rsi_volume",
        execute_paper=False,
        notify_paper=False,
        now=NOW,
    )
    assert notifications == []
    with pytest.raises(ValueError):
        technical.scan(
            symbols=["EXAMPLE"],
            mode="swing",
            execute_paper=True,
            notify_paper=False,
            now=NOW,
        )
    technical.repository.close()


def test_report_navigation_carries_the_scanner_strategy_and_horizon():
    from webapp.stock_report_workspace import navigation_state

    state = navigation_state("EXAMPLE", "tf_long_ema100_200", "long_term")
    assert state["stock_report_horizon"] == "Long Term"
    assert "100/200" in state["stock_report_strategy_long_term"]
    assert state["scanner_section"] == "Stock report"
    assert "stock_report_horizon" not in navigation_state(
        "EXAMPLE", "tf_intraday_ema9_20_momentum", "intraday"
    )


def test_scanner_report_shortcut_switches_tab_before_widgets_are_created(monkeypatch):
    import streamlit as st
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(
        st,
        "switch_page",
        lambda page: st.session_state.update(shortcut_destination=page),
    )
    app = AppTest.from_string("""
import streamlit as st
from webapp.stock_report_workspace import report_link
tabs = st.tabs(["Scan stocks", "Stock report"],
               key="scanner_section", on_change="rerun")
with tabs[0]:
    if tabs[0].open:
        report_link(["EXAMPLE"], key="shortcut_test",
                    strategy_id="tf_long_ema100_200", horizon="long_term")
    """).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state["scanner_section"] == "Stock report"
    assert app.session_state["tf_selected_stock_symbol"] == "EXAMPLE"
    assert app.session_state["stock_report_horizon"] == "Long Term"
    assert app.session_state["shortcut_destination"] == (
        "webapp/pages/technical_scanner.py"
    )
