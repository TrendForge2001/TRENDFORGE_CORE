from __future__ import annotations

import pandas as pd

from engines.big_shark_engine import BigSharkEngine
from providers.enrichment_adapters import YahooInstitutionalEnrichmentProvider
from providers.screener_shareholding import (
    ScreenerShareholdingProvider,
    build_screener_shareholding_evidence,
    parse_screener_shareholding,
)


SAMPLE_HTML = """
<html>
<body>
<section id="shareholding">
  <h2>Shareholding Pattern</h2>
  <div>
    <table class="data-table">
      <thead>
        <tr>
          <th></th>
          <th>Dec 2025</th>
          <th>Mar 2026</th>
          <th>Jun 2026</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>Promoters +</td><td>0.00%</td><td>0.00%</td><td>0.00%</td></tr>
        <tr><td>FIIs +</td><td>20.64%</td><td>26.07%</td><td>29.85%</td></tr>
        <tr><td>DIIs +</td><td>59.16%</td><td>54.35%</td><td>50.80%</td></tr>
        <tr><td>Public +</td><td>20.03%</td><td>19.38%</td><td>19.15%</td></tr>
      </tbody>
    </table>
  </div>
</section>
</body>
</html>
"""


def test_parse_screener_shareholding_extracts_quarterly_categories():
    periods = parse_screener_shareholding(SAMPLE_HTML)

    assert len(periods) == 3
    assert periods[-1] == {
        "as_of": "2026-06-30",
        "promoter": 0.0,
        "fii": 29.85,
        "dii": 50.8,
        "public": 19.15,
    }


def test_build_screener_evidence_computes_latest_changes():
    periods = parse_screener_shareholding(SAMPLE_HTML)
    evidence = build_screener_shareholding_evidence(periods)

    snapshot = evidence["shareholding_snapshot"]
    assert snapshot["source"] == "SCREENER_SHAREHOLDING"
    assert snapshot["as_of"] == "2026-06-30"
    assert snapshot["fii"] == 29.85
    assert snapshot["dii"] == 50.8

    changes = {
        row["category"]: row["change"]
        for row in evidence["holding_changes"]
    }
    assert changes["FII"] == 3.78
    assert changes["DII"] == -3.55
    assert changes["PROMOTER"] == 0.0

    assert evidence["_meta"]["periods_parsed"] == 3


class FakeResponse:
    def __init__(self, text=SAMPLE_HTML, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        return FakeResponse()


def test_screener_provider_fetches_consolidated_company_page():
    session = FakeSession()
    provider = ScreenerShareholdingProvider(session=session)

    evidence = provider.get("mcx")

    assert evidence["shareholding_snapshot"]["fii"] == 29.85
    assert evidence["shareholding_snapshot"]["dii"] == 50.8
    assert session.calls == [
        "https://www.screener.in/company/MCX/consolidated/"
    ]


class EmptyYahoo:
    def institutional_holders(self, symbol):
        return pd.DataFrame()

    def mutualfund_holders(self, symbol):
        return pd.DataFrame()


class EmptyNSE:
    def shareholding_filings(self, symbol):
        return []

    def public_document(self, url):
        raise AssertionError("NSE document should not be requested")

    def bulk_deals(self, days=30):
        return {"data": []}

    def block_deals(self, days=30):
        return {"data": []}


class BlockedBSE:
    def shareholding_filings(self, symbol):
        raise RuntimeError("HTTP 403")

    def public_document(self, url):
        raise AssertionError("BSE document should not be requested")


class FakeScreener:
    def get(self, symbol):
        assert symbol == "MCX"
        return build_screener_shareholding_evidence(
            parse_screener_shareholding(SAMPLE_HTML)
        )


def test_big_shark_uses_screener_only_after_exchange_paths_have_no_evidence():
    adapter = YahooInstitutionalEnrichmentProvider(
        yahoo=EmptyYahoo(),
        nse=EmptyNSE(),
        bse=BlockedBSE(),
        screener=FakeScreener(),
    )

    data = adapter.get("MCX")

    assert data["_meta"]["nse_shareholding_runtime_verified"] is True
    assert data["_meta"]["bse_shareholding_runtime_verified"] is False
    assert data["_meta"]["screener_shareholding_runtime_verified"] is True
    assert data["_meta"]["shareholding_source"] == "SCREENER_SHAREHOLDING"
    assert data["_meta"]["shareholding_periods_parsed"] == 3
    assert data["shareholding_snapshot"]["fii"] == 29.85
    assert data["shareholding_snapshot"]["dii"] == 50.8

    result = BigSharkEngine().evaluate(
        {
            "symbol": "MCX",
            **data,
        }
    )

    assert result.metrics["data_quality"] is True
    assert result.metrics["ownership"]["fii"] == 29.85
    assert result.metrics["ownership"]["dii"] == 50.8
    assert result.confidence > 0
