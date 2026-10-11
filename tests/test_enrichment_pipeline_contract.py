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


class HealthyProvider(Provider):
    def health(self):
        return {"status": "runtime_verified"}


class DegradedProvider(Provider):
    def health(self):
        return {
            "status": "degraded",
            "last_error": "upstream blocked",
        }


def test_enricher_health_reports_fallback_chain_not_only_primary():
    from reconstruction.provider_registry import ProviderRegistry

    registry = ProviderRegistry()
    registry.register(
        "sector",
        HealthyProvider({"sector": "IT"}),
        priority=10,
        name="snapshot:sector",
    )
    registry.register(
        "sector",
        DegradedProvider(None),
        priority=100,
        name="live:sector",
    )
    registry.register(
        "fundamentals",
        HealthyProvider({}),
        priority=10,
    )
    registry.register(
        "corporate_actions",
        HealthyProvider([]),
        priority=10,
    )
    registry.register(
        "big_shark",
        HealthyProvider({}),
        priority=10,
    )

    health = StockEnricher(registry=registry).health()

    assert health["status"] == "degraded"
    assert health["provider_health"]["sector"]["status"] == (
        "runtime_verified"
    )
    chain = health["provider_chain_health"]["sector"]
    assert [row["name"] for row in chain] == [
        "snapshot:sector",
        "live:sector",
    ]
    assert chain[1]["status"] == "degraded"
    assert chain[1]["last_error"] == "upstream blocked"
