"""Closed-fill visibility, consistent accounting and independent conditional plans."""

import io
import secrets
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.paper_automation_router import paper_automation_router
from core.database import initialize_database
from database.database import Database
from database.repositories.trade_repository import TradeRepository
from services.conditional_stock_plan import conditional_plan
from services.paper_trade_reports import PaperTradeReports
from services.paper_trading_runtime import PaperTradingRuntime
from webapp.paper_trade_reports import workbook
from webapp.trade_table import COLUMNS, broker_frame, stock_frame, trade_frame

NOW = datetime(2026, 11, 23, 10, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def book(tmp_path):
    path = str(tmp_path / "paper.db")
    initialize_database(path)
    db = Database(path)
    repo = TradeRepository(db)
    runtime = PaperTradingRuntime(trades=repo)
    yield SimpleNamespace(runtime=runtime), repo
    db.close()


def saved(repo, symbol="EXAMPLE", *, qty=1, at=None, side="BUY"):
    return repo.save(
        symbol,
        side,
        qty,
        100,
        stoploss=90,
        target=130,
        created_at=(at or NOW - timedelta(days=5)).isoformat(),
        trade_mode="swing",
    )


def test_all_time_closed_history_survives_runtime_restart_and_exceeds_200(book):
    paper, repo = book
    for i in range(205):
        key = saved(repo, f"S{i:03}")
        repo.close_trade(key, 110, closed_at=(NOW - timedelta(days=2)).isoformat())
    paper.runtime.restore_open()
    report = PaperTradeReports(paper).statement(now=NOW)
    assert report["summary"]["closed_fills"] == 205
    assert report["summary"]["realized_pnl"] == 2050
    assert report["portfolio"]["positions"] == []
    assert len(report["closed_trades"]) == 205
    assert len(list(repo.closed_trades())) == 205
    assert not PaperTradeReports(paper).statement(period="daily", now=NOW)[
        "closed_trades"
    ]


def test_partial_realisation_and_cashflows_are_attributed_to_the_open_parent(book):
    paper, repo = book
    parent = saved(repo)
    child = saved(repo)
    repo.close_trade(child, 110, closed_at=NOW.isoformat())
    repo.db.execute(
        "UPDATE trade_history SET parent_trade_id=? WHERE id=?", (parent, child)
    )
    old = saved(repo)
    repo.close_trade(old, 105, closed_at=(NOW - timedelta(days=1)).isoformat())
    paper.runtime.restore_open()
    paper.runtime.monitor({"EXAMPLE": 105}, now=NOW)
    report = PaperTradeReports(paper).statement(period="daily", now=NOW)
    row = report["portfolio"]["positions"][0]
    assert row["realized_pnl"] == 10
    assert row["unrealized_pnl"] == 5
    assert row["buy_value"] == 200
    assert row["sell_value"] == 110
    assert row["quantity"] == 1
    assert report["summary"]["realized_pnl"] == 10
    assert report["closed_trades"][0]["parent_trade_id"] == parent
    assert report["closed_trades"][0]["ltp"] is None


def test_short_legacy_fill_keeps_correct_buy_and_sell_values(book):
    paper, repo = book
    key = saved(repo, side="SHORT")
    repo.close_trade(key, 90, closed_at=NOW.isoformat())
    report = PaperTradeReports(paper).statement(now=NOW)
    row = report["closed_trades"][0]
    assert (row["buy_value"], row["sell_value"], row["realized_pnl"]) == (90, 100, 10)


def test_compact_columns_and_workbook_preserve_history_without_extra_ui_fields(book):
    paper, repo = book
    key = saved(repo)
    repo.close_trade(key, 110, closed_at=NOW.isoformat())
    report = PaperTradeReports(paper).statement(now=NOW)
    frame = trade_frame(report["closed_trades"], closed=True)
    assert tuple(frame.columns) == COLUMNS
    assert "EXAMPLE" in frame.index[0]
    assert frame.iloc[0]["OPEN PRICE"] == 100
    assert frame.iloc[0]["CLOSE PRICE"] == 110
    assert frame.iloc[0]["STOPLOSS"] == 90
    wb = load_workbook(io.BytesIO(workbook(report)), read_only=True)
    assert len(list(wb["Closed paper trades"].values)) == 2
    assert "Recorded fill evidence" in wb.sheetnames


def test_trade_report_api_is_private_read_only_and_defaults_to_all_time(
    book, monkeypatch
):
    paper, repo = book
    key = saved(repo)
    repo.close_trade(key, 110, closed_at=(NOW - timedelta(days=2)).isoformat())
    key_value = secrets.token_urlsafe(32)
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", key_value)
    app = FastAPI()
    app.include_router(
        paper_automation_router(
            automation_getter=lambda: None, paper_getter=lambda: paper
        )
    )
    with TestClient(app) as client:
        assert client.get("/paper/trade-reports").status_code == 401
        headers = {"X-TrendForge-Admin-Key": key_value}
        response = client.get("/paper/trade-reports", headers=headers)
        assert response.status_code == 200
        assert response.json()["period"] == "all"
        assert response.json()["summary"]["closed_fills"] == 1
        assert (
            client.get(
                "/paper/trade-reports?period=invalid", headers=headers
            ).status_code
            == 422
        )
    assert len(list(repo.closed_trades())) == 1


def candles(count=20):
    return [
        {"date": f"2026-11-{i + 1:02}", "low": 90.0, "high": 110.0, "close": 100.0}
        for i in range(count)
    ]


def test_unmatched_reference_has_future_entry_support_stop_and_exact_2r():
    plan = conditional_plan(candles(), horizon="short_term")
    assert plan["entry"] == 110.11
    assert plan["stop_reference"] == 89.91
    assert plan["targets"][0] == 150.51
    assert plan["reviewable_setup"] is False
    assert plan["execution_enabled"] is False
    frame = stock_frame(
        {
            "symbol": "UNMATCHED",
            "conditional_plan": plan,
            "trade_plan": {"entry": None},
            "market_quote": {"last_price": 101},
        }
    )
    assert tuple(frame.columns) == COLUMNS
    assert frame.iloc[0]["OPEN PRICE"] == 110.11
    assert frame.iloc[0]["CLOSE PRICE"] == 150.51
    assert frame.iloc[0]["LTP"] == 101
    assert frame.iloc[0]["QTY"] is None
    assert frame.iloc[0]["REALISED P&L"] is None


def test_missing_prices_do_not_fabricate_a_conditional_entry():
    plan = conditional_plan(candles(19), horizon="long_term")
    assert plan["entry"] is None
    assert plan["status"] == "DATA_UNAVAILABLE"


def test_broker_net_pnl_does_not_become_unrealised_or_realised_by_guessing():
    frame = broker_frame(
        [
            {
                "tradingsymbol": "EXAMPLE",
                "exchange": "NFO",
                "quantity": 1,
                "average_price": 100,
                "last_price": 110,
                "pnl": 5,
                "realised": 2,
                "unrealised": 3,
                "buy_value": 100,
                "sell_value": 50,
            }
        ]
    )
    assert frame.iloc[0]["REALISED P&L"] == 2
    assert frame.iloc[0]["UNREALISED P&L"] == 3
    assert frame.iloc[0]["SEGMENT"] is None
    separate_books = broker_frame(
        [
            {
                "tradingsymbol": "SAME",
                "exchange": "NSE",
                "product": product,
                "quantity": 1,
                "average_price": 100,
            }
            for product in ("MIS", "CNC")
        ]
    )
    assert separate_books.index.is_unique
    assert tuple(separate_books.columns) == COLUMNS


def test_unmatched_report_keeps_the_strategy_wait_and_adds_only_reference_prices():
    import pandas as pd

    from services.stock_report_service import StockReportService

    dates = pd.bdate_range(end=NOW.date(), periods=260, tz="Asia/Kolkata")
    data = pd.DataFrame(
        {"open": 100.0, "high": 110.0, "low": 90.0, "close": 100.0, "volume": 1000.0},
        index=dates,
    )
    calls = []

    def scan(**kwargs):
        calls.append(kwargs)
        return {"results": []}

    technical = SimpleNamespace(
        scan=scan, market_data=SimpleNamespace(candles=lambda *a, **k: data)
    )
    quote_at = NOW - timedelta(hours=2)

    class Quote:
        def quote(self, instruments):
            return {"NSE:EXAMPLE": {"last_price": 101.0, "timestamp": quote_at}}

    service = StockReportService(
        lambda: technical,
        company_provider=SimpleNamespace(get=lambda *a, **k: {}),
        quote_getter=Quote,
    )
    report = service.build("EXAMPLE", now=NOW)
    assert report["conditional_plan"]["entry"] == 110.11
    assert report["conditional_plan"]["targets"] == [150.51]
    assert report["trade_plan"]["entry"] is None
    assert report["trade_plan"]["reviewable_setup"] is False
    assert report["technical"]["signal"] != "BUY"
    assert report["market_quote"]["last_price"] == 101
    assert report["market_quote"]["fresh_for_order"] is False
    assert report["market_quote"]["timestamp"] == quote_at.isoformat()
    assert calls[0]["execute_paper"] is False
    assert calls[0]["notify_paper"] is False


def test_trade_report_ui_defaults_all_time_and_uses_only_the_compact_columns(
    book, monkeypatch
):
    from streamlit.testing.v1 import AppTest

    paper, repo = book
    key = saved(repo)
    repo.close_trade(key, 110, closed_at=(NOW - timedelta(days=2)).isoformat())
    reads = []

    def get_json(path, **kwargs):
        reads.append((path, kwargs.get("params")))
        assert path == "/paper/trade-reports"
        return PaperTradeReports(paper).statement(
            period=kwargs["params"]["period"], now=NOW
        )

    monkeypatch.setattr(
        "webapp.runtime.api_client", lambda: SimpleNamespace(get_json=get_json)
    )
    monkeypatch.setenv("TRENDFORGE_WEBAPP_ACCESS_KEY", secrets.token_urlsafe(32))
    app = AppTest.from_string("""
from webapp.runtime import api_client
from webapp.paper_trade_reports import render_trade_reports
render_trade_reports(api_client())
""").run()
    assert not app.exception
    assert app.selectbox[0].value == "all"
    assert tuple(app.dataframe[0].value.columns) == COLUMNS
    assert len(app.dataframe[0].value) == 1
    app.selectbox[0].select("daily").run()
    assert not app.exception
    assert not app.dataframe
    assert reads[-1] == ("/paper/trade-reports", {"period": "daily"})
