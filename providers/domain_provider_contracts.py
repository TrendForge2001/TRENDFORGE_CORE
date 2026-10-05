"""Domain-specific provider contracts that are intentionally separate from market data."""
from __future__ import annotations

from typing import Any, Protocol


class NewsProvider(Protocol):
    """Provider contract for symbol/company news retrieval."""

    def get_news(self, symbol: str, **kwargs: Any) -> Any:
        ...


class CorporateActionProvider(Protocol):
    """Provider contract for corporate-action retrieval."""

    def get_corporate_actions(self, symbol: str, **kwargs: Any) -> Any:
        ...
