from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.application_factory import ApplicationFactory
from engines.fundamental_contract import FundamentalInputContract
from providers.composite_fundamental_provider import CompositeFundamentalProvider
from providers.screener_provider import ScreenerProvider
from providers.tijori_provider import TijoriFundamentalProvider
from reconstruction.enrichment import StockEnricher


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_tijori_provider_uses_configured_endpoint_and_canonical_mapping():
    response = FakeResponse(
        {
            "data": {
                "metrics": {
                    "roce": 16.0,
                    "roe_ratio": 0.18,
                    "sales_growth": 12.0,
                    "profit_growth": 15.0,
                    "eps_growth": 11.0,
                    "debt_equity": 0.45,
                    "promoter_holding": 50.3,
                    "pledged": 0.0,
                },
                "as_of": "2026-09-30",
            }
        }
    )
    session = FakeSession(response)
    provider = TijoriFundamentalProvider(
        url_template="https://enterprise.example/fundamentals/{symbol}",
        api_key="secret",
        field_map={
            "roce": "metrics.roce",
            "roe": {"path": "metrics.roe_ratio", "scale": 100},
            "sales_growth": "metrics.sales_growth",
            "profit_growth": "metrics.profit_growth",
            "eps_growth": "metrics.eps_growth",
            "debt_equity": "metrics.debt_equity",
            "promoter_holding": "metrics.promoter_holding",
            "pledged": "metrics.pledged",
        },
        session=session,
    )

    data = provider.get("reliance")

    assert data["roce"] == 16.0
    assert data["roe"] == 18.0
    assert data["promoter_holding"] == 50.3
    assert data["pledged"] == 0.0
    assert data["_meta"]["missing"] == []
    assert session.calls[0][0].endswith("/RELIANCE")
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer secret"


def test_tijori_provider_is_fail_closed_when_enterprise_endpoint_not_configured():
    provider = TijoriFundamentalProvider(url_template=None, api_key=None)

    assert provider.configured is False
    assert provider.get("RELIANCE") is None
    assert provider.health()["status"] == "not_configured"


def test_screener_provider_reads_user_generated_csv_export(tmp_path: Path):
    export = tmp_path / "screener.csv"
    pd.DataFrame(
        [
            {
                "NSE Code": "RELIANCE",
                "ROCE": 14.2,
                "ROE": 9.8,
                "Sales growth": 6.5,
                "Profit growth": 4.1,
                "EPS growth": 4.0,
                "Debt to equity": 0.42,
                "Promoter holding": 50.1,
                "Pledged": 0.0,
            }
        ]
    ).to_csv(export, index=False)

    provider = ScreenerProvider(export_path=str(export))
    data = provider.get("RELIANCE")

    assert data["roce"] == 14.2
    assert data["roe"] == 9.8
    assert data["debt_equity"] == 0.42
    assert data["promoter_holding"] == 50.1
    assert data["pledged"] == 0.0
    assert data["_meta"]["missing"] == []
    assert data["_meta"]["source"] == "screener_premium_csv_export"


class StaticProvider:
    def __init__(self, name, values):
        self.NAME = name
        self.values = values

    def get(self, symbol):
        return {
            **self.values,
            "_meta": {
                "provider": self.NAME,
                "stale": False,
                "missing": [],
                "warnings": [],
            },
        }

    def health(self):
        return {"status": "configured", "provider": self.NAME}


def test_composite_provider_uses_tijori_first_and_screener_to_fill_missing_fields():
    tijori = StaticProvider(
        "TijoriFundamentalProvider",
        {
            "roce": 16.0,
            "roe": 18.0,
            "sales_growth": 12.0,
            "profit_growth": 15.0,
            "eps_growth": 11.0,
            "debt_equity": 0.45,
        },
    )
    screener = StaticProvider(
        "ScreenerProvider",
        {
            "roce": 99.0,
            "promoter_holding": 50.3,
            "pledged": 0.0,
        },
    )
    provider = CompositeFundamentalProvider([tijori, screener])

    data = provider.get("RELIANCE")

    assert data["roce"] == 16.0
    assert data["promoter_holding"] == 50.3
    assert data["pledged"] == 0.0
    assert data["_meta"]["missing"] == []
    assert data["_meta"]["field_sources"]["roce"] == "TijoriFundamentalProvider"
    assert data["_meta"]["field_sources"]["pledged"] == "ScreenerProvider"


def test_enricher_flattens_complete_composite_fundamentals_into_engine_contract():
    provider = StaticProvider(
        "CompositeFundamentalProvider",
        {
            "roce": 16.0,
            "roe": 18.0,
            "sales_growth": 12.0,
            "profit_growth": 15.0,
            "eps_growth": 11.0,
            "debt_equity": 0.45,
            "promoter_holding": 50.3,
            "pledged": 0.0,
        },
    )
    enricher = StockEnricher(providers={"fundamentals": provider})

    result = enricher.enrich({"symbol": "RELIANCE"})
    merged = enricher.merge({"symbol": "RELIANCE"}, result)
    report = FundamentalInputContract().validate(merged)

    assert report.ready is True
    assert merged["roce"] == 16.0
    assert merged["promoter_holding"] == 50.3
    assert merged["pledged"] == 0.0


def test_application_factory_wires_tijori_then_screener_without_yahoo(
    monkeypatch,
    tmp_path: Path,
):
    export = tmp_path / "screener.csv"
    export.write_text("NSE Code,ROCE\nRELIANCE,10\n", encoding="utf-8")

    monkeypatch.setenv(
        "TIJORI_FUNDAMENTALS_URL_TEMPLATE",
        "https://enterprise.example/fundamentals/{symbol}",
    )
    monkeypatch.setenv("TIJORI_API_KEY", "secret")
    monkeypatch.setenv("SCREENER_EXPORT_PATH", str(export))

    factory = ApplicationFactory()
    specs = factory.enricher.registry.providers("fundamentals")

    assert len(specs) == 1
    composite = specs[0].provider
    assert isinstance(composite, CompositeFundamentalProvider)
    assert [provider.NAME for provider in composite.providers] == [
        "TijoriFundamentalProvider",
        "ScreenerProvider",
    ]
    assert "Yahoo" not in repr(composite.health())


def test_application_factory_leaves_fundamentals_unconfigured_without_sources(monkeypatch):
    for name in (
        "TIJORI_FUNDAMENTALS_URL_TEMPLATE",
        "TIJORI_API_KEY",
        "SCREENER_EXPORT_PATH",
        "SCREENER_EXPORT_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    factory = ApplicationFactory()

    assert factory.enricher is None
