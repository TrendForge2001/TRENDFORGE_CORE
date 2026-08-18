"""Provider registry and resolution layer for TrendForge enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    field: str
    provider: Any
    priority: int = 100
    name: str = "provider"


class ProviderRegistry:
    """Resolve primary/fallback providers without coupling engines to vendors."""

    FIELDS = (
        "fundamentals", "corporate_actions", "big_shark",
        "market_regime", "sector", "risk",
    )

    def __init__(self) -> None:
        self._providers: dict[str, list[ProviderSpec]] = {field: [] for field in self.FIELDS}

    def register(self, field: str, provider: Any, *, priority: int = 100, name: str | None = None) -> None:
        if field not in self._providers:
            raise ValueError(f"Unsupported enrichment field: {field}")
        self._providers[field].append(ProviderSpec(field, provider, priority, name or provider.__class__.__name__))
        self._providers[field].sort(key=lambda item: item.priority)

    def providers(self, field: str) -> tuple[ProviderSpec, ...]:
        return tuple(self._providers.get(field, ()))

    def resolve(self) -> dict[str, Any]:
        return {field: specs[0].provider for field, specs in self._providers.items() if specs}

    def describe(self) -> dict[str, list[dict[str, Any]]]:
        return {
            field: [{"name": spec.name, "priority": spec.priority} for spec in specs]
            for field, specs in self._providers.items()
        }

    def health(self) -> dict[str, Any]:
        return {
            "configured_fields": [field for field, specs in self._providers.items() if specs],
            "missing_fields": [field for field, specs in self._providers.items() if not specs],
            "providers": self.describe(),
        }


__all__ = ["ProviderRegistry", "ProviderSpec"]
