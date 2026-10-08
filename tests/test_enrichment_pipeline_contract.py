from __future__ import annotations

from reconstruction.enrichment import StockEnricher
from reconstruction.provider_registry import ProviderRegistry


class Provider:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def get(self, symbol, payload=None):
        self.calls += 1
        return self.value


def test_enrichment_preserves_prepared_payload_and_does_not_refetch():
    provider = Provider({"pe": 12})
    enricher = StockEnricher(
        providers={"fundamentals": provider}
    )
    result = enricher.enrich(
        {
            "symbol": "ABC",
            "fundamentals": {"pe": 10},
        }
    )

    assert result.data["fundamentals"] == {"pe": 10}
    assert provider.calls == 0


def test_enrichment_populates_missing_fields_from_registered_provider():
    provider = Provider({"pe": 12})
    enricher = StockEnricher(
        providers={"fundamentals": provider}
    )
    result = enricher.enrich({"symbol": "ABC"})

    assert result.data["fundamentals"] == {"pe": 12}
    assert provider.calls == 1


def test_enrichment_reports_only_missing_external_fields():
    enricher = StockEnricher(
        registry=ProviderRegistry()
    )
    result = enricher.enrich({"symbol": "ABC"})

    assert "provider_not_configured:fundamentals" in result.warnings
    assert "provider_not_configured:big_shark" in result.warnings
    assert "provider_not_configured:sector" in result.warnings
    assert "provider_not_configured:corporate_actions" in result.warnings
    assert "provider_not_configured:market_regime" not in result.warnings
    assert "provider_not_configured:risk" not in result.warnings


def test_registry_health_separates_external_from_derived_fields():
    health = ProviderRegistry().health()

    assert set(health["missing_fields"]) == {
        "fundamentals",
        "corporate_actions",
        "big_shark",
        "sector",
    }
    assert set(health["derived_fields"]) == {
        "market_regime",
        "risk",
    }


def test_merge_records_enrichment_provenance_and_failures():
    provider = Provider({"pe": 12})
    enricher = StockEnricher(
        providers={"fundamentals": provider}
    )
    result = enricher.enrich({"symbol": "ABC"})
    merged = enricher.merge(
        {"symbol": "ABC"},
        result,
    )

    assert merged["fundamentals"] == {"pe": 12}
    assert "enrichment_warnings" in merged
    assert "enrichment_failures" in merged
    assert "enrichment_provenance" in merged
