from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.application_factory import ApplicationFactory
from engines.fundamental_contract import FundamentalInputContract
from providers.yahoo_fundamental_provider import YahooFundamentalProvider
from reconstruction.enrichment import StockEnricher


class FakeYahoo:
    def __init__(self, info=None, financials=None, balance_sheet=None):
        self.info = info or {}
        self._financials = financials if financials is not None else pd.DataFrame()
        self._balance_sheet = balance_sheet if balance_sheet is not None else pd.DataFrame()
        self.calls = {"info": 0, "financials": 0, "balance_sheet": 0}

    def company_info(self, symbol):
        self.calls["info"] += 1
        return dict(self.info)

    def financials(self, symbol):
        self.calls["financials"] += 1
        return self._financials.copy()

    def balance_sheet(self, symbol):
        self.calls["balance_sheet"] += 1
        return self._balance_sheet.copy()


def fiscal_timestamp(year=2026, month=3, day=31):
    return datetime(year, month, day, tzinfo=timezone.utc).timestamp()


def test_yahoo_provider_normalizes_supported_metrics_and_caches():
    yahoo = FakeYahoo(info={
        "lastFiscalYearEnd": fiscal_timestamp(),
        "returnOnCapitalEmployed": 0.16,
        "returnOnEquity": 0.18,
        "revenueGrowth": 0.12,
        "earningsGrowth": 0.15,
        "earningsQuarterlyGrowth": 0.11,
        "debtToEquity": 45.0,
    })
    provider = YahooFundamentalProvider(yahoo, cache_ttl_seconds=3600)

    first = provider.get("reliance")
    second = provider.get("RELIANCE")

    assert first["roce"] == 16.0
    assert first["roe"] == 18.0
    assert first["sales_growth"] == 12.0
    assert first["profit_growth"] == 15.0
    assert first["eps_growth"] == 11.0
    assert first["debt_equity"] == 0.45
    assert first["_meta"]["stale"] is False
    assert first["_meta"]["missing"] == ["promoter_holding", "pledged"]
    assert second == first
    assert yahoo.calls == {"info": 1, "financials": 1, "balance_sheet": 1}


def test_yahoo_provider_derives_metrics_from_statements():
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
    provider = YahooFundamentalProvider(
        FakeYahoo(
            info={"lastFiscalYearEnd": fiscal_timestamp()},
            financials=financials,
            balance_sheet=balance_sheet,
        )
    )

    data = provider.get("ABC")

    assert data["roce"] == 15.0
    assert data["roe"] == 24.0
    assert data["sales_growth"] == 20.0
    assert data["profit_growth"] == 20.0
    assert data["eps_growth"] == 20.0
    assert data["debt_equity"] == 0.3


class StaticFundamentals:
    def __init__(self, value):
        self.value = value

    def get(self, symbol, payload=None):
        return self.value


def test_enricher_flattens_fresh_partial_fundamentals_and_keeps_missing_fields_explicit():
    fundamentals = {
        "roce": 16.0,
        "roe": 18.0,
        "sales_growth": 12.0,
        "profit_growth": 15.0,
        "eps_growth": 11.0,
        "debt_equity": 0.45,
        "_meta": {
            "provider": "YahooFundamentalProvider",
            "as_of": "2026-03-31T00:00:00+00:00",
            "age_days": 189,
            "stale": False,
            "missing": ["promoter_holding", "pledged"],
            "warnings": [
                "promoter_holding_requires_authoritative_india_source",
                "pledged_shares_require_authoritative_india_source",
            ],
        },
    }
    enricher = StockEnricher(
        providers={"fundamentals": StaticFundamentals(fundamentals)}
    )

    result = enricher.enrich({"symbol": "RELIANCE"})
    merged = enricher.merge({"symbol": "RELIANCE"}, result)
    report = FundamentalInputContract().validate(merged)

    assert merged["roce"] == 16.0
    assert merged["debt_equity"] == 0.45
    assert report.ready is False
    assert report.missing == ["promoter_holding", "pledged"]
    assert merged["fundamental_data_quality"]["provider"] == "YahooFundamentalProvider"
    assert merged["fundamental_data_quality"]["stale"] is False
    assert (
        "fundamentals:promoter_holding_requires_authoritative_india_source"
        in merged["enrichment_warnings"]
    )


def test_stale_fundamentals_are_not_flattened_into_engine_contract():
    fundamentals = {
        "roce": 99.0,
        "roe": 99.0,
        "sales_growth": 99.0,
        "profit_growth": 99.0,
        "eps_growth": 99.0,
        "debt_equity": 0.0,
        "promoter_holding": 99.0,
        "pledged": 0.0,
        "_meta": {
            "provider": "Test",
            "stale": True,
            "missing": [],
            "warnings": ["fundamental_snapshot_stale_or_undated"],
        },
    }
    enricher = StockEnricher(
        providers={"fundamentals": StaticFundamentals(fundamentals)}
    )

    merged = enricher.merge(
        {"symbol": "ABC"},
        enricher.enrich({"symbol": "ABC"}),
    )
    report = FundamentalInputContract().validate(merged)

    assert report.ready is False
    assert set(report.missing) == set(FundamentalInputContract.REQUIRED)
    assert merged["fundamental_data_quality"]["stale"] is True


def test_application_factory_configures_public_fundamental_provider_without_network_call():
    factory = ApplicationFactory()
    providers = factory.enricher.registry.providers("fundamentals")

    assert len(providers) == 1
    assert providers[0].name == "YahooFundamentalProvider"
    health = factory.enricher.health()
    assert "fundamentals" in health["configured_fields"]
    assert health["provider_health"]["fundamentals"]["network_probe"] is False
    assert health["provider_health"]["fundamentals"]["authoritative_promoter_data"] is False
