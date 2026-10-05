from __future__ import annotations

from typing import Any, Dict, List, Protocol


class NewsProvider(Protocol):
    """Provider contract for symbol-scoped news retrieval."""

    def news(self, symbol: str) -> List[Dict[str, Any]]:
        ...
