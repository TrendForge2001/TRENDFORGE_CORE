"""Domain-specific provider contracts for enrichment services.

These contracts deliberately remain separate from MarketDataAdapter: news and
corporate actions are enrichment domains, not candle/market-data concerns.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence


class NewsProvider(Protocol):
    """Provider contract consumed by NewsService."""

    def news(self, symbol: str) -> Sequence[Mapping[str, Any]]: ...


class CorporateActionProvider(Protocol):
    """Provider contract consumed by corporate-action services/engines."""

    def corporate_actions(self) -> Sequence[Mapping[str, Any]]: ...


__all__ = ["NewsProvider", "CorporateActionProvider"]
