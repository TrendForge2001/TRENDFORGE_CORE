"""R72.6 regression: five technical tabs, official NIFTY 50 and truthful P&L."""
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from providers.nse_broad_market_constituents import (
    INDEX_CONFIGS,
    NSEBroadMarketConstituentProvider,
    normalize_index_name,
)
from webapp.navigation import NAVIGATION_SPEC
from webapp.paper_excel import paper_daily_xlsx


def test_five_pages_only_and_no_fundamental_entries():
    assert len(NAVIGATION_SPEC) == 5
    assert tuple(NAVIGATION_SPEC) == (
        "Watchlist", "Technical Scanner", "Backtesting",
        "Live Paper Trading", "Live Kite Session",
    )
    for pages in NAVIGATION_SPEC.values():
        assert len(pages) == 1
        assert Path("webapp", pages[0].path).exists()
    active = " ".join(page.path for group in NAVIGATION_SPEC.values() for page in group)
    assert "fundamental" not in active.lower()
    assert "corporate_action" not in active.lower()


def test_streamlit_uses_five_visible_top_level_tabs():
    source = Path("webapp/app.py").read_text(encoding="utf-8")
    assert 'st.navigation(pages, position="top")' in source
    assert 'if not render_access_gate():' in source


def test_nifty50_is_official_validated_index():
    assert normalize_index_name("NIFTY50") == "NIFTY 50"
    assert normalize_index_name("50") == "NIFTY 50"
    config = INDEX_CONFIGS["NIFTY 50"]
    assert config.nominal_count == 50
    assert config.minimum_count == 50
    assert config.source_url.endswith("/ind_nifty50list.csv")


def test_nifty50_provider_does_not_invent_members_when_nse_fails(tmp_path):
    class FailingSession:
        headers = {}

        def get(self, *_args, **_kwargs):
            raise ConnectionError("NSE blocked")
    provider = NSEBroadMarketConstituentProvider(
        session=FailingSession(), cache_dir=tmp_path, timeout=1
    )
    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        provider.load("NIFTY 50")


def test_paper_daily_excel_has_real_workbook_and_correct_daily_realized():
    statement = {
        "scope": "paper_trading_closed_trades",
        "period": "daily", "period_end": "2026-10-22T15:30:00+05:30",
        "date_basis": "closed_at_with_legacy_entry_fallback",
        "summary": {"trade_count": 1, "gross_profit": 150, "gross_loss": 0, "net_pnl": 150},
        "trades": [{"symbol": "SBIN", "pnl": 150, "closed_at": "2026-10-22"}],
        "daily": [{"date": "2026-10-22", "trade_count": 1, "net_pnl": 150}],
    }
    portfolio = {"open_positions": 1, "unrealized_pnl": -20, "positions": [{"symbol": "RELIANCE", "unrealized_pnl": -20}]}
    data = paper_daily_xlsx(statement, portfolio)
    assert data[:2] == b"PK"
    with pd.ExcelFile(BytesIO(data)) as book:
        assert set(book.sheet_names) == {
            "Daily P&L", "Daily Closed Trades", "Open Paper Portfolio", "Daily Aggregates"
        }
        summary = pd.read_excel(book, sheet_name="Daily P&L").set_index("Metric")["Value"]
        assert float(summary["Realized net P&L (₹)"]) == 150
        assert float(summary["Open unrealized P&L (₹)"]) == -20


def test_daily_export_rejects_nondaily_or_nonpaper_data():
    with pytest.raises(ValueError):
        paper_daily_xlsx({"scope": "live", "period": "daily"}, {})
