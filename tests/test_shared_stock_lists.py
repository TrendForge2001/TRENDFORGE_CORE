"""Shared list state, bounded sources and explicit equity/index separation."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from api.app import create_app
from api.research_reports_router import ResearchRequest
from config.stock_lists import (
    EQUITY_STOCK_LISTS,
    GROUP_SUFFIX,
    STOCK_LISTS,
    resolve_stock_list,
    stock_list_label,
)
from providers.stock_list_catalog import (
    EQUITY_URL,
    FO_URL,
    StockListCatalogProvider,
    parse_bse_members,
    parse_fo_members,
)
from services.trading_workspace_service import TradingWorkspaceService


def members(count=30):
    return [
        {
            "symbol": f"S{i:03d}",
            "name": f"Company {i} Ltd.",
            "sector": "Banking" if i % 2 else "Technology",
        }
        for i in range(count)
    ]


def bse_table(count=30):
    return (
        "<table><tr><th>Company</th><th>Weightage*</th></tr>"
        + "".join(
            f"<tr><td><a>Company {i} Limited</a></td><td>1%</td></tr>"
            for i in range(count)
        )
        + "</table>"
    )


def fo_files():
    fo = 'NSE permitted lots\nCompany,"SYMBOL",NOV-26\nIndex,NIFTY,75\n' + "".join(
        f"Company {i},S{i:03d},100\n" for i in range(100)
    )
    equity = "SYMBOL,NAME OF COMPANY,SERIES\n" + "".join(
        f"S{i:03d},Company {i},EQ\n" for i in range(100)
    )
    return fo, equity


def test_catalog_covers_screenshots_and_keeps_nifty500():
    from config.stock_lists import NSE_ALL_INDICES

    assert len(NSE_ALL_INDICES) == 139
    assert set(NSE_ALL_INDICES) <= set(STOCK_LISTS)
    assert len(STOCK_LISTS) == 149
    assert {
        "Major Indices",
        "Global Indices",
        "NIFTY NEXT 50",
        "BSE SENSEX",
        "BSE BANKEX",
        "NSE F&O Stocks",
        "NIFTY 500",
    } <= set(STOCK_LISTS)
    for base in (
        "NIFTY 50",
        "BSE SENSEX",
        "NIFTY NEXT 50",
        "NIFTY LARGEMIDCAP 250",
        "NSE F&O Stocks",
    ):
        assert STOCK_LISTS[base + GROUP_SUFFIX].base == base
        assert STOCK_LISTS[base + GROUP_SUFFIX].grouped
    assert resolve_stock_list("Bank Nifty")[0] == "NIFTY BANK"
    assert resolve_stock_list("Nifty FinNifty")[0] == "NIFTY FINANCIAL SERVICES"


@pytest.mark.parametrize("label", ["Major Indices", "Global Indices"])
def test_index_references_never_enter_equity_research(label):
    assert label not in EQUITY_STOCK_LISTS
    with pytest.raises(ValidationError):
        ResearchRequest(
            symbols=["TCS"],
            strategy_id="research",
            horizon="short_term",
            stock_list=label,
        )
    service = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=SimpleNamespace(),
    )
    result = service.watchlist(label)
    assert result["kind"] == "index"
    assert result["rows"]
    assert result["quote_status"] == "not_requested"


def test_fno_underlyings_exclude_index_derivatives_and_preserve_all_equities():
    fo, equity = fo_files()
    result = parse_fo_members(fo, equity)
    assert len(result) == 100
    assert "NIFTY" not in {m["symbol"] for m in result}
    assert result[-1]["symbol"] == "S099"
    with pytest.raises(ValueError, match="incomplete"):
        parse_fo_members(fo, "\n".join(equity.splitlines()[:50]))


def test_bse_mapping_is_complete_unique_and_never_substitutes_another_index():
    result = parse_bse_members(bse_table(), members(), base="BSE SENSEX")
    assert len(result) == 30
    assert [m["symbol"] for m in result] == [m["symbol"] for m in members()]
    with pytest.raises(ValueError, match="incomplete"):
        parse_bse_members(bse_table(29), members(), base="BSE SENSEX")
    with pytest.raises(ValueError, match="unique NSE"):
        parse_bse_members(
            bse_table().replace("Company 0 Limited", "Unknown Limited"),
            members(),
            base="BSE SENSEX",
        )
    with pytest.raises(ValueError, match="duplicate"):
        parse_bse_members(
            bse_table().replace("Company 29 Limited", "Company 0 Limited"),
            members(),
            base="BSE SENSEX",
        )


def test_grouped_provider_reuses_membership_and_preserves_validated_stale_cache(
    tmp_path,
):
    class Session:
        fail = False
        calls = []

        def get(self, url, **kwargs):
            self.calls.append(url)
            if self.fail:
                raise RuntimeError("private upstream response")
            return SimpleNamespace(text=bse_table(), raise_for_status=lambda: None)

    session = Session()
    nse = SimpleNamespace(
        session=session, cache_dir=tmp_path, load=lambda name: {"members": members()}
    )
    provider = StockListCatalogProvider(nse)
    first = provider.load("BSE SENSEX")
    grouped = provider.load("BSE SENSEX" + GROUP_SUFFIX)
    assert first["members"] == grouped["members"]
    assert grouped["grouped"] and len(session.calls) == 1
    session.fail = True
    provider = StockListCatalogProvider(nse)
    stale = provider.load("BSE SENSEX")
    assert stale["stale"] and stale["members"] == first["members"]
    assert "private" not in str(stale)
    assert provider.load("BSE SENSEX")["stale"]
    assert len(session.calls) == 2
    # A snapshot from another index must never be accepted under this filename.
    path = tmp_path / "bse_sensex_catalog.json"
    path.write_text(
        path.read_text().replace(
            '"base_index": "BSE SENSEX"', '"base_index": "BSE BANKEX"'
        )
    )
    assert provider._saved("BSE SENSEX") is None


def test_fno_provider_uses_official_sources_and_sector_enrichment(tmp_path):
    fo, equity = fo_files()
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(
            text=fo if url == FO_URL else equity, raise_for_status=lambda: None
        )

    nse = SimpleNamespace(
        session=SimpleNamespace(get=get),
        cache_dir=tmp_path,
        load=lambda name: {"members": members(100)},
    )
    result = StockListCatalogProvider(nse).load("NSE F&O Stocks")
    assert calls == [FO_URL, EQUITY_URL]
    assert len(result["members"]) == 100
    assert result["members"][0]["sector"] == "Technology"


def test_watchlist_batches_quotes_without_dropping_members():
    calls = []
    data = members(525)
    provider = SimpleNamespace(
        safe_quote=lambda instruments: (
            calls.append(instruments) or {s: {"last_price": 100.0} for s in instruments}
        )
    )
    service = TradingWorkspaceService(
        intelligence_getter=lambda: None,
        paper_getter=lambda: None,
        universe_provider=SimpleNamespace(load=lambda name: {"members": data}),
        provider_factory=SimpleNamespace(quote=lambda: provider),
    )
    result = service.watchlist("NIFTY 500")
    assert [len(c) for c in calls] == [500, 25]
    assert result["count"] == result["quoted_count"] == 525


def test_catalog_api_lists_groups_without_loading_market_data():
    factory = SimpleNamespace(technical_trading_service=lambda: None)
    response = TestClient(create_app(factory)).get("/workspace/stock-lists")
    assert response.status_code == 200
    assert {r["name"] for r in response.json()["lists"]} == set(STOCK_LISTS)


def test_shared_picker_persists_between_pages_and_does_not_fetch_on_refresh(
    monkeypatch,
):
    from webapp import stock_lists

    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def get_json(self, path, **kwargs):
            calls.append(path)
            return {
                "rows": [{"symbol": "TCS", "stock_name": "TCS", "sector": "IT"}],
                "kind": "equity",
                "source": "test",
            }

    monkeypatch.setattr("webapp.api_client.TrendForgeApi", Client)
    stock_lists.load_members.clear()
    app = AppTest.from_string(
        "import streamlit as st\n"
        "from webapp.stock_lists import render_shared_stock_lists\n"
        "render_shared_stock_lists('https://test.invalid')\n"
        "st.radio('Page', ['Watchlist', 'Reports', 'Paper'])\n"
    ).run(timeout=15)
    app.selectbox[0].select("NIFTY NEXT 50" + GROUP_SUFFIX).run(timeout=15)
    app.radio[0].set_value("Reports").run(timeout=15)
    assert app.selectbox[0].value == "NIFTY NEXT 50" + GROUP_SUFFIX
    assert calls == []
    app.toggle[0].set_value(True).run(timeout=15)
    assert calls == []
    next(b for b in app.button if b.label == "Load / refresh members").click().run(
        timeout=15
    )
    assert len(calls) == 1 and not app.exception
    app.run(timeout=15)
    assert len(calls) == 1
    next(b for b in app.button if b.label == "Use this stock").click().run(timeout=15)
    assert app.session_state["tf_selected_stock_symbol"] == "TCS"
    assert "tf_paper_order_symbol" not in app.session_state
    assert "tf_live_preview_symbol" not in app.session_state
    assert len(calls) == 1
    stock_lists.load_members.clear()


def test_every_active_page_renders_shared_catalog_after_login(monkeypatch):
    from webapp.api_client import ApiError
    from webapp.navigation import all_pages

    def unavailable(*args, **kwargs):
        raise ApiError("Offline membership fixture")

    def no_mutation(*args, **kwargs):
        pytest.fail("Changing lists or pages must never submit orders or research")

    monkeypatch.setattr("webapp.app.render_access_gate", lambda: True)
    monkeypatch.setattr("webapp.app.render_sidebar_status", lambda **kw: None)
    monkeypatch.setattr("webapp.api_client.TrendForgeApi.get_json", unavailable)
    monkeypatch.setattr("webapp.api_client.TrendForgeApi.post_json", no_mutation)
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "streamlit_app.py").run(timeout=15)
    app.selectbox[0].select("NIFTY NEXT 50").run(timeout=15)
    for page in all_pages():
        app.switch_page("webapp/" + page.path).run(timeout=15)
        assert not app.exception
        pickers = [s for s in app.selectbox if s.label == "Stock list"]
        if page.path == "pages/technical_scanner.py":
            assert len(pickers) == 1
            assert set(pickers[0].options) == {stock_list_label(k) for k in STOCK_LISTS}
            assert pickers[0].value == "NIFTY NEXT 50"
        else:
            assert not pickers
