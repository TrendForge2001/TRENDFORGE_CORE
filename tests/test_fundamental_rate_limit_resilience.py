from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from providers.yahoo_fundamental_provider import YahooFundamentalProvider
from providers.yfinance_provider import YahooFinanceProvider


def fiscal_timestamp(year=2026, month=3, day=31):
    return datetime(year, month, day, tzinfo=timezone.utc).timestamp()


def complete_statements():
    columns = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
    financials = pd.DataFrame(
        {
            columns[0]: [120.0, 1200.0, 120.0, 12.0],
            columns[1]: [100.0, 1000.0, 100.0, 10.0],
        },
        index=["EBIT", "Total Revenue", "Net Income", "Diluted EPS"],
    )
    balance_sheet = pd.DataFrame(
        {
            columns[0]: [1000.0, 200.0, 500.0, 150.0],
            columns[1]: [900.0, 180.0, 450.0, 135.0],
        },
        index=["Total Assets", "Current Liabilities", "Stockholders Equity", "Total Debt"],
    )
    return financials, balance_sheet


class InfoWouldRateLimit:
    def __init__(self):
        self.financials_frame, self.balance_sheet_frame = complete_statements()
        self.calls = {"financials": 0, "balance_sheet": 0, "info": 0}

    def financials(self, symbol):
        self.calls["financials"] += 1
        return self.financials_frame.copy()

    def balance_sheet(self, symbol):
        self.calls["balance_sheet"] += 1
        return self.balance_sheet_frame.copy()

    def company_info(self, symbol):
        self.calls["info"] += 1
        raise RuntimeError("Too Many Requests. Rate limited. Try after a while.")


def test_statement_first_path_avoids_rate_limited_info_when_not_needed():
    source = InfoWouldRateLimit()
    provider = YahooFundamentalProvider(source)

    data = provider.get("RELIANCE")

    assert data["roce"] == 15.0
    assert data["roe"] == 24.0
    assert data["sales_growth"] == 20.0
    assert data["profit_growth"] == 20.0
    assert data["eps_growth"] == 20.0
    assert data["debt_equity"] == 0.3
    assert data["_meta"]["source_errors"] == {}
    assert data["_meta"]["statement_first"] is True
    assert source.calls == {"financials": 1, "balance_sheet": 1, "info": 0}


class StatementsPartiallyRateLimited:
    def __init__(self):
        _, self.balance_sheet_frame = complete_statements()
        self.calls = {"financials": 0, "balance_sheet": 0, "info": 0}

    def financials(self, symbol):
        self.calls["financials"] += 1
        raise RuntimeError("429 Too Many Requests")

    def balance_sheet(self, symbol):
        self.calls["balance_sheet"] += 1
        return self.balance_sheet_frame.copy()

    def company_info(self, symbol):
        self.calls["info"] += 1
        return {
            "lastFiscalYearEnd": fiscal_timestamp(),
            "returnOnCapitalEmployed": 0.16,
            "returnOnEquity": 0.18,
            "revenueGrowth": 0.12,
            "earningsGrowth": 0.15,
            "earningsQuarterlyGrowth": 0.11,
            "debtToEquity": 45.0,
        }


def test_source_rate_limit_isolated_and_info_backfills_missing_metrics():
    source = StatementsPartiallyRateLimited()
    provider = YahooFundamentalProvider(source)

    data = provider.get("RELIANCE")

    assert data["roce"] == 16.0
    assert data["roe"] == 18.0
    assert data["sales_growth"] == 12.0
    assert data["profit_growth"] == 15.0
    assert data["eps_growth"] == 11.0
    # Balance-sheet derivation is preferred over the .info backfill.
    assert data["debt_equity"] == 0.3
    assert data["_meta"]["stale"] is False
    assert "financials" in data["_meta"]["source_errors"]
    assert "yahoo_rate_limited:financials" in data["_meta"]["warnings"]
    assert source.calls == {"financials": 1, "balance_sheet": 1, "info": 1}


class EverythingRateLimited:
    def __init__(self):
        self.calls = {"financials": 0, "balance_sheet": 0, "info": 0}

    def financials(self, symbol):
        self.calls["financials"] += 1
        raise RuntimeError("Too Many Requests")

    def balance_sheet(self, symbol):
        self.calls["balance_sheet"] += 1
        raise RuntimeError("Too Many Requests")

    def company_info(self, symbol):
        self.calls["info"] += 1
        raise RuntimeError("Too Many Requests")


def test_all_rate_limits_return_quality_metadata_and_short_cache_instead_of_raising():
    source = EverythingRateLimited()
    provider = YahooFundamentalProvider(
        source,
        partial_cache_ttl_seconds=3600,
    )

    first = provider.get("RELIANCE")
    second = provider.get("RELIANCE")

    assert first == second
    assert first["_meta"]["stale"] is True
    assert set(first["_meta"]["missing"]) == {
        "roce",
        "roe",
        "sales_growth",
        "profit_growth",
        "eps_growth",
        "debt_equity",
        "promoter_holding",
        "pledged",
    }
    assert "yahoo_rate_limited:financials" in first["_meta"]["warnings"]
    assert "yahoo_rate_limited:balance_sheet" in first["_meta"]["warnings"]
    assert "yahoo_rate_limited:company_info" in first["_meta"]["warnings"]
    assert source.calls == {"financials": 1, "balance_sheet": 1, "info": 1}


def test_yfinance_fundamental_resources_are_cached_for_repeated_scans(monkeypatch):
    provider = YahooFinanceProvider()
    provider.cache.clear()
    calls = {"ticker": 0}

    class FakeTicker:
        info = {"returnOnEquity": 0.18}
        financials = pd.DataFrame({"2026": [1.0]}, index=["Net Income"])
        balance_sheet = pd.DataFrame({"2026": [1.0]}, index=["Total Assets"])

    def fake_ticker(symbol):
        calls["ticker"] += 1
        return FakeTicker()

    monkeypatch.setattr(provider, "ticker", fake_ticker)

    provider.company_info("RELIANCE")
    provider.company_info("RELIANCE")
    provider.financials("RELIANCE")
    provider.financials("RELIANCE")
    provider.balance_sheet("RELIANCE")
    provider.balance_sheet("RELIANCE")

    assert calls["ticker"] == 3
