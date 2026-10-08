from __future__ import annotations

import pandas as pd

from providers.enrichment_adapters import (
    CorporateActionEnrichmentProvider,
    YahooInstitutionalEnrichmentProvider,
    YahooSectorEnrichmentProvider,
)
from reconstruction.enrichment import StockEnricher


class FakeCorporateProvider:
    def corporate_actions(self):
        return [
            {
                "symbol": "ABC",
                "subject": "Dividend",
                "purpose": "Final dividend declared",
                "date": "2026-10-08",
            },
            {
                "symbol": "XYZ",
                "subject": "Board Meeting",
                "purpose": "Results",
                "date": "2026-10-09",
            },
        ]


class FakeYahoo:
    def institutional_holders(self, symbol):
        return pd.DataFrame(
            [
                {
                    "Holder": "Institution A",
                    "% Out": 0.08,
                    "Value": 1000000,
                    "Date Reported": "2026-09-30",
                }
            ]
        )

    def mutualfund_holders(self, symbol):
        return pd.DataFrame(
            [
                {
                    "Holder": "Fund A",
                    "% Out": 0.03,
                    "Value": 500000,
                    "Date Reported": "2026-09-30",
                }
            ]
        )

    def company_info(self, symbol):
        return {
            "sector": "Healthcare",
            "industry": "Drug Manufacturers",
        }

    def historical_data(
        self,
        symbol,
        period="6mo",
        interval="1d",
        auto_adjust=False,
    ):
        close = [100 + index for index in range(90)]
        volume = [1000 + index * 5 for index in range(90)]
        if symbol == "^NSEI":
            close = [200 + index * 0.5 for index in range(90)]
        return pd.DataFrame(
            {
                "Close": close,
                "Volume": volume,
            }
        )


def test_corporate_action_adapter_filters_symbol_and_normalizes_title():
    provider = CorporateActionEnrichmentProvider(
        FakeCorporateProvider()
    )

    actions = provider.get("ABC")

    assert len(actions) == 1
    assert actions[0]["symbol"] == "ABC"
    assert "Dividend" in actions[0]["title"]
    assert actions[0]["date"] == "2026-10-08"


def test_yahoo_institutional_adapter_keeps_conservative_classification():
    provider = YahooInstitutionalEnrichmentProvider(
        yahoo=FakeYahoo()
    )

    data = provider.get("ABC")

    assert data is not None
    assert len(data["institutional_holders"]) == 2
    assert data["institutional_holders"][0]["category"] == "INSTITUTIONAL"
    assert data["institutional_holders"][1]["category"] == "MUTUAL FUND"
    assert "fii" not in data
    assert "dii" not in data


def test_yahoo_sector_adapter_returns_engine_usable_snapshot():
    provider = YahooSectorEnrichmentProvider(
        yahoo=FakeYahoo()
    )

    snapshot = provider.get("ABC")

    assert snapshot is not None
    assert snapshot["sector"] == "Healthcare"
    assert snapshot["proxy_symbol"] == "^CNXPHARMA"
    assert snapshot["change_1d"] is not None
    assert snapshot["change_1m"] is not None
    assert snapshot["market_return"] is not None


def test_stock_enricher_flattens_big_shark_inputs_for_engine():
    provider = YahooInstitutionalEnrichmentProvider(
        yahoo=FakeYahoo()
    )
    enricher = StockEnricher(
        providers={
            "big_shark": provider,
        }
    )

    result = enricher.enrich(
        {
            "symbol": "ABC",
            "fundamentals": {},
            "corporate_actions": [],
            "sector": {
                "sector": "Healthcare",
                "change_1d": 1.0,
            },
        }
    )
    merged = enricher.merge({"symbol": "ABC"}, result)

    assert "big_shark" in merged
    assert "institutional_holders" in merged
    assert len(merged["institutional_holders"]) == 2


def test_enrichment_does_not_require_derived_market_regime_or_risk():
    enricher = StockEnricher(
        providers={
            "fundamentals": lambda symbol, payload: {},
            "corporate_actions": lambda symbol, payload: [],
            "big_shark": lambda symbol, payload: {},
            "sector": lambda symbol, payload: {
                "sector": "Healthcare",
                "change_1d": 1.0,
            },
        }
    )

    result = enricher.enrich({"symbol": "ABC"})

    assert "provider_not_configured:market_regime" not in result.warnings
    assert "provider_not_configured:risk" not in result.warnings
    assert enricher.health()["missing_fields"] == []


class FailingCorporateProvider:
    def __init__(self):
        self.calls = 0

    def corporate_actions(self, **kwargs):
        self.calls += 1
        raise RuntimeError("NSE returned a non-JSON response")


def test_corporate_action_failure_enters_short_cooldown_without_hammering():
    provider = FailingCorporateProvider()
    adapter = CorporateActionEnrichmentProvider(
        provider,
        failure_cooldown_seconds=120,
    )

    import pytest

    with pytest.raises(RuntimeError, match="non-JSON"):
        adapter.get("ABC")

    with pytest.raises(RuntimeError, match="cooldown active"):
        adapter.get("XYZ")

    assert provider.calls == 1
    health = adapter.health()
    assert health["status"] == "degraded"
    assert health["retry_after_seconds"] > 0


class RateLimitedYahoo:
    def __init__(self):
        self.holder_calls = 0

    def institutional_holders(self, symbol):
        self.holder_calls += 1
        raise RuntimeError(
            "Too Many Requests. Rate limited. Try after a while."
        )

    def mutualfund_holders(self, symbol):
        raise AssertionError("mutual fund call should not follow rate limit")


class FakeNSEDeals:
    def __init__(self):
        self.bulk_calls = 0
        self.block_calls = 0

    def bulk_deals(self, days=30):
        self.bulk_calls += 1
        return {
            "data": [
                {
                    "symbol": "ABC",
                    "clientName": "Large Fund",
                    "buySell": "BUY",
                    "quantityTraded": 200000,
                    "tradePrice": 125.5,
                    "date": "08-Oct-2026",
                }
            ]
        }

    def block_deals(self, days=30):
        self.block_calls += 1
        return {"data": []}


def test_big_shark_uses_nse_deals_when_yahoo_is_rate_limited():
    yahoo = RateLimitedYahoo()
    nse = FakeNSEDeals()
    adapter = YahooInstitutionalEnrichmentProvider(
        yahoo=yahoo,
        nse=nse,
        yahoo_rate_limit_cooldown=900,
    )

    first = adapter.get("ABC")
    second = adapter.get("XYZ")

    assert first is not None
    assert len(first["deals"]) == 1
    assert first["deals"][0]["side"] == "BUY"
    assert first["_meta"]["nse_deals_runtime_verified"] is True
    assert first["_meta"]["yahoo_retry_after_seconds"] > 0

    assert second is not None
    assert "deals" not in second
    assert yahoo.holder_calls == 1
    assert nse.bulk_calls == 1
    assert nse.block_calls == 1
    assert adapter.health()["status"] == "runtime_verified"


class FakeNSEQuote:
    def __init__(self):
        self.calls = 0

    def equity_quote(self, symbol):
        self.calls += 1
        return {
            "industryInfo": {
                "macro": "Healthcare",
                "sector": "Healthcare",
                "industry": "Pharmaceuticals",
                "basicIndustry": "Pharmaceuticals",
            }
        }


class HistoryOnlyYahoo:
    def __init__(self):
        self.info_calls = 0
        self.history_calls = []

    def company_info(self, symbol):
        self.info_calls += 1
        raise AssertionError("Yahoo metadata should not be required")

    def historical_data(
        self,
        symbol,
        period="6mo",
        interval="1d",
        auto_adjust=False,
    ):
        self.history_calls.append(symbol)
        close = [100 + index for index in range(90)]
        volume = [1000 + index for index in range(90)]
        return pd.DataFrame(
            {
                "Close": close,
                "Volume": volume,
            }
        )


def test_sector_prefers_nse_metadata_and_caches_benchmark_history():
    yahoo = HistoryOnlyYahoo()
    nse = FakeNSEQuote()
    adapter = YahooSectorEnrichmentProvider(
        yahoo=yahoo,
        nse=nse,
    )

    first = adapter.get("ABC")
    second = adapter.get("XYZ")

    assert first is not None
    assert second is not None
    assert first["sector"] == "Healthcare"
    assert first["proxy_symbol"] == "^CNXPHARMA"
    assert first["_meta"]["metadata_source"] == "NSE"
    assert yahoo.info_calls == 0
    assert yahoo.history_calls.count("^NSEI") == 1
    assert yahoo.history_calls.count("^CNXPHARMA") == 1
    assert adapter.health()["status"] == "runtime_verified"
