"""Explicit bootstrap for confirmed TrendForge enrichment services."""

from __future__ import annotations

from typing import Any

from .provider_adapters import build_confirmed_adapters
from .provider_registry import ProviderRegistry


def build_provider_registry(*, fundamental_service: Any = None, corporate_action_service: Any = None,
                             sector_service: Any = None, big_shark_provider: Any = None,
                             market_regime_provider: Any = None, risk_provider: Any = None,
                             priorities: dict[str, int] | None = None) -> ProviderRegistry:
    """Build an explicit registry; only supplied providers are registered."""
    registry = ProviderRegistry()
    priorities = priorities or {}
    adapters = build_confirmed_adapters(fundamental_service=fundamental_service,
                                         corporate_action_service=corporate_action_service,
                                         sector_service=sector_service)
    for field, provider in adapters.items():
        registry.register(field, provider, priority=priorities.get(field, 100), name=provider.name)
    optional = {"big_shark": big_shark_provider, "market_regime": market_regime_provider, "risk": risk_provider}
    for field, provider in optional.items():
        if provider is not None:
            registry.register(field, provider, priority=priorities.get(field, 100), name=provider.__class__.__name__)
    return registry


def registry_health(registry: ProviderRegistry) -> dict[str, Any]:
    health = registry.health()
    health["ready_for_enrichment"] = bool(health["configured_fields"])
    return health


__all__ = ["build_provider_registry", "registry_health"]
