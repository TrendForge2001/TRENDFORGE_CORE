from __future__ import annotations

import pandas as pd

from engines.big_shark_engine import BigSharkEngine
from providers.bse_shareholding import (
    BSEShareholdingProvider,
    build_bse_shareholding_evidence,
    parse_scripcode_search,
    parse_shareholding_ixbrl,
)
from providers.enrichment_adapters import YahooInstitutionalEnrichmentProvider


def sample_ixbrl(
    promoter: float,
    fii: float,
    dii: float,
    public: float,
) -> str:
    return f"""<!doctype html>
<html
 xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
 xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp/test">
<body>
<xbrli:context id="c-promoter">
  <xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">in-bse-shp:ShareholdingOfPromoterAndPromoterGroupMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity>
</xbrli:context>
<xbrli:context id="c-public">
  <xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">in-bse-shp:PublicShareholdingMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity>
</xbrli:context>
<xbrli:context id="c-fii">
  <xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">in-bse-shp:PublicShareholdingMember</xbrldi:explicitMember>
    <xbrldi:explicitMember dimension="in-bse-shp:InstitutionAxis">in-bse-shp:InstitutionsForeignMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity>
</xbrli:context>
<xbrli:context id="c-dii">
  <xbrli:entity><xbrli:segment>
    <xbrldi:explicitMember dimension="in-bse-shp:CategoryAxis">in-bse-shp:PublicShareholdingMember</xbrldi:explicitMember>
    <xbrldi:explicitMember dimension="in-bse-shp:InstitutionAxis">in-bse-shp:InstitutionsDomesticMember</xbrldi:explicitMember>
  </xbrli:segment></xbrli:entity>
</xbrli:context>

<ix:nonFraction name="in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares" contextRef="c-promoter">{promoter}</ix:nonFraction>
<ix:nonFraction name="in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares" contextRef="c-public">{public}</ix:nonFraction>
<ix:nonFraction name="in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares" contextRef="c-fii">{fii}</ix:nonFraction>
<ix:nonFraction name="in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares" contextRef="c-dii">{dii}</ix:nonFraction>
</body>
</html>
"""


def test_bse_scrip_search_resolves_exact_symbol():
    response = (
        "<span><strong>MCX</strong> "
        "INE745G01043 534091 Multi Commodity Exchange</span>"
    )

    assert parse_scripcode_search(response, "MCX") == "534091"


def test_bse_ixbrl_parser_extracts_official_categories():
    parsed = parse_shareholding_ixbrl(
        sample_ixbrl(
            promoter=0.0,
            fii=29.84,
            dii=50.79,
            public=99.81,
        )
    )

    assert parsed["promoter"] == 0.0
    assert parsed["fii"] == 29.84
    assert parsed["dii"] == 50.79
    assert parsed["public"] == 99.81


def test_bse_evidence_builder_computes_qoq_changes():
    latest = "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/534091_latest.html"
    previous = "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/534091_previous.html"

    filings = [
        {
            "EndDate": "2026-06-30T00:00:00",
            "XBRLAttachment": "/XBRLFILES/SHPXBRLDataXML/534091_latest.html",
            "xbrl": latest,
            "IsXBRL": 1,
        },
        {
            "EndDate": "2026-03-31T00:00:00",
            "XBRLAttachment": "/XBRLFILES/SHPXBRLDataXML/534091_previous.html",
            "xbrl": previous,
            "IsXBRL": 1,
        },
    ]
    documents = {
        latest: sample_ixbrl(0.0, 29.84, 50.79, 99.81),
        previous: sample_ixbrl(0.0, 28.50, 49.25, 99.80),
    }

    evidence, errors = build_bse_shareholding_evidence(
        filings,
        lambda url: documents[url],
    )

    assert errors == []
    assert evidence["shareholding_snapshot"]["fii"] == 29.84
    assert evidence["shareholding_snapshot"]["dii"] == 50.79
    assert evidence["shareholding_snapshot"]["promoter"] == 0.0
    assert evidence["_meta"]["source"] == "BSE_REG31_IXBRL"
    assert evidence["_meta"]["filings_parsed"] == 2

    changes = {
        row["category"]: row["change"]
        for row in evidence["holding_changes"]
    }
    assert changes["FII"] == 1.34
    assert changes["DII"] == 1.54
    assert changes["PROMOTER"] == 0.0


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


class FakeBSE:
    def __init__(self):
        self.latest = (
            "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/"
            "534091_latest.html"
        )
        self.previous = (
            "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/"
            "534091_previous.html"
        )

    def shareholding_filings(self, symbol):
        assert symbol == "MCX"
        return [
            {
                "EndDate": "2026-06-30T00:00:00",
                "xbrl": self.latest,
                "IsXBRL": 1,
            },
            {
                "EndDate": "2026-03-31T00:00:00",
                "xbrl": self.previous,
                "IsXBRL": 1,
            },
        ]

    def public_document(self, url):
        if url == self.latest:
            return sample_ixbrl(0.0, 29.84, 50.79, 99.81)
        return sample_ixbrl(0.0, 28.50, 49.25, 99.80)


def test_big_shark_falls_back_to_bse_when_nse_has_zero_filings():
    adapter = YahooInstitutionalEnrichmentProvider(
        yahoo=EmptyYahoo(),
        nse=EmptyNSE(),
        bse=FakeBSE(),
    )

    data = adapter.get("MCX")

    assert data["shareholding_snapshot"]["fii"] == 29.84
    assert data["shareholding_snapshot"]["dii"] == 50.79
    assert data["shareholding_snapshot"]["promoter"] == 0.0
    assert data["_meta"]["nse_shareholding_runtime_verified"] is True
    assert data["_meta"]["bse_shareholding_runtime_verified"] is True
    assert data["_meta"]["shareholding_source"] == "BSE_REG31_IXBRL"

    result = BigSharkEngine().evaluate(
        {
            "symbol": "MCX",
            **data,
        }
    )

    assert result.metrics["data_quality"] is True
    assert result.metrics["ownership"]["fii"] == 29.84
    assert result.metrics["ownership"]["dii"] == 50.79
    assert result.confidence > 0


class FakeResponse:
    def __init__(self, *, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json"}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class ScripListSession:
    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, dict(params or {})))

        if url.endswith("/ListofScripData/w"):
            return FakeResponse(
                payload=[
                    {
                        "scrip_id": "MCX",
                        "SCRIP_CD": "534091",
                        "Scrip_Name": "Multi Commodity Exchange",
                    },
                    {
                        "scrip_id": "RELIANCE",
                        "SCRIP_CD": "500325",
                    },
                ]
            )

        raise AssertionError(
            "PeerSmartSearch should not be needed when active scrip list resolves"
        )


def test_bse_resolves_symbol_from_active_scrip_list_before_peer_search():
    session = ScripListSession()
    provider = BSEShareholdingProvider(session=session)

    code = provider.resolve_scripcode("mcx")

    assert code == "534091"
    assert len(session.calls) == 1
    url, params = session.calls[0]
    assert url.endswith("/ListofScripData/w")
    assert params == {
        "segment": "Equity",
        "status": "Active",
    }


def test_bse_active_scrip_list_is_cached_for_symbol_resolution():
    session = ScripListSession()
    provider = BSEShareholdingProvider(session=session)

    assert provider.resolve_scripcode("MCX") == "534091"
    assert provider.resolve_scripcode("RELIANCE") == "500325"

    assert len(session.calls) == 1
