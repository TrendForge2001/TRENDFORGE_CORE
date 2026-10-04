from __future__ import annotations

from core.application_factory import ApplicationFactory


class _ConfiguredComponent:
    def __init__(self, status: str):
        self.status = status

    def health(self):
        return {"status": self.status}


class _ProviderFactory:
    runtime_config = None

    def __init__(self, market_status: str):
        self._market = _ConfiguredComponent(market_status)

    def market_data(self):
        return self._market


class _DomainProviders:
    def news(self):
        return object()

    def corporate_actions(self):
        return object()


def _factory(scanner_status: str, market_status: str, monkeypatch):
    factory = ApplicationFactory(
        provider_factory=_ProviderFactory(market_status),
        domain_provider_factory=_DomainProviders(),
    )
    scanner = _ConfiguredComponent(scanner_status)
    monkeypatch.setattr(factory, "scanner_service", lambda: scanner)
    monkeypatch.setattr(factory, "news_provider", lambda: object())
    monkeypatch.setattr(factory, "corporate_action_provider", lambda: object())
    return factory


def test_application_health_does_not_promote_configured_components_to_healthy(monkeypatch):
    monkeypatch.setattr(
        "core.application_factory.database_health",
        lambda: {"status": "ready"},
    )
    monkeypatch.setattr(
        "core.application_factory.runtime_configuration_health",
        lambda _: {"status": "configured"},
    )

    factory = _factory("configured", "configured", monkeypatch)

    health = factory.health()

    assert health["status"] == "degraded"


def test_application_health_requires_runtime_healthy_components(monkeypatch):
    monkeypatch.setattr(
        "core.application_factory.database_health",
        lambda: {"status": "ready"},
    )
    monkeypatch.setattr(
        "core.application_factory.runtime_configuration_health",
        lambda _: {"status": "configured"},
    )

    factory = _factory("healthy", "healthy", monkeypatch)

    health = factory.health()

    assert health["status"] == "healthy"
