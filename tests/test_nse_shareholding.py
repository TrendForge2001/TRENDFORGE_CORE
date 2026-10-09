from __future__ import annotations

from providers.enrichment_adapters import (
    YahooInstitutionalEnrichmentProvider,
)
from providers.nse_shareholding import (
    build_shareholding_evidence,
    parse_shareholding_xbrl,
)
from engines.big_shark_engine import BigSharkEngine


def sample_xbrl(promoter: float, fii: float, dii: float, public: float) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl
    xmlns:xbrli="http://www.xbrl.org/2003/instance"
    xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
    xmlns:in-bse-shp="http://example.test/shp">
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
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="c-promoter">{promoter}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="c-public">{public}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="c-fii">{fii}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="c-dii">{dii}</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
</xbrli:xbrl>
"""


def test_shareholding_xbrl_parser_normalizes_fraction_taxonomy():
    parsed = parse_shareholding_xbrl(
        sample_xbrl(
            promoter=0.50,
            fii=0.12,
            dii=0.08,
            public=0.50,
        )
    )

    assert parsed["promoter"] == 50.0
    assert parsed["fii"] == 12.0
    assert parsed["dii"] == 8.0
    assert parsed["public"] == 50.0


def test_build_shareholding_evidence_computes_qoq_deltas():
    latest_url = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_LATEST.xml"
    previous_url = "https://nsearchives.nseindia.com/corporate/xbrl/SHP_PREVIOUS.xml"

    filings = [
        {"date": "30-SEP-2026", "xbrl": latest_url},
        {"date": "30-JUN-2026", "xbrl": previous_url},
    ]
    documents = {
        latest_url: sample_xbrl(0.50, 0.12, 0.08, 0.50),
        previous_url: sample_xbrl(0.49, 0.10, 0.09, 0.51),
    }

    evidence, errors = build_shareholding_evidence(
        filings,
        lambda url: documents[url],
    )

    assert errors == []
    assert evidence["shareholding_snapshot"]["promoter"] == 50.0
    assert evidence["shareholding_snapshot"]["fii"] == 12.0
    assert evidence["shareholding_snapshot"]["dii"] == 8.0

    changes = {
        row["category"]: row["change"]
        for row in evidence["holding_changes"]
    }
    assert changes["PROMOTER"] == 1.0
    assert changes["FII"] == 2.0
    assert changes["DII"] == -1.0
    assert evidence["promoter"]["current"] == 50.0
    assert evidence["promoter"]["previous"] == 49.0


class EmptyYahoo:
    def institutional_holders(self, symbol):
        import pandas as pd
        return pd.DataFrame()

    def mutualfund_holders(self, symbol):
        import pandas as pd
        return pd.DataFrame()


class ShareholdingNSE:
    def __init__(self):
        self.latest_url = (
            "https://nsearchives.nseindia.com/corporate/xbrl/SHP_LATEST.xml"
        )
        self.previous_url = (
            "https://nsearchives.nseindia.com/corporate/xbrl/SHP_PREVIOUS.xml"
        )

    def shareholding_filings(self, symbol):
        return [
            {"date": "30-SEP-2026", "xbrl": self.latest_url},
            {"date": "30-JUN-2026", "xbrl": self.previous_url},
        ]

    def public_document(self, url):
        if url == self.latest_url:
            return sample_xbrl(0.50, 0.12, 0.08, 0.50)
        return sample_xbrl(0.49, 0.10, 0.09, 0.51)

    def bulk_deals(self, days=30):
        return {"data": []}

    def block_deals(self, days=30):
        return {"data": []}


def test_institutional_adapter_emits_engine_usable_nse_shareholding():
    provider = YahooInstitutionalEnrichmentProvider(
        yahoo=EmptyYahoo(),
        nse=ShareholdingNSE(),
    )

    data = provider.get("ABC")

    assert data["shareholding_snapshot"]["fii"] == 12.0
    assert data["shareholding_snapshot"]["dii"] == 8.0
    assert data["promoter"]["current"] == 50.0
    assert len(data["holding_changes"]) == 3
    assert data["_meta"]["nse_shareholding_runtime_verified"] is True
    assert data["_meta"]["coverage"]["shareholding_snapshot"] is True


def test_big_shark_engine_scores_official_shareholding_evidence():
    provider = YahooInstitutionalEnrichmentProvider(
        yahoo=EmptyYahoo(),
        nse=ShareholdingNSE(),
    )
    data = provider.get("ABC")

    result = BigSharkEngine().evaluate(
        {
            "symbol": "ABC",
            **data,
        }
    )

    assert result.metrics["data_quality"] is True
    assert result.metrics["ownership"]["fii"] == 12.0
    assert result.metrics["ownership"]["dii"] == 8.0
    assert result.metrics["holding_changes"]["fii"] == 2.0
    assert result.metrics["holding_changes"]["dii"] == -1.0
    assert result.confidence > 0
