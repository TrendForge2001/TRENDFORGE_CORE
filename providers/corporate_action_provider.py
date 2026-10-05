from __future__ import annotations

from typing import Any, Dict, List, Protocol


class CorporateActionProvider(Protocol):
    """Provider contract for corporate-action retrieval."""

    def corporate_actions(self) -> List[Dict[str, Any]]:
        ...
