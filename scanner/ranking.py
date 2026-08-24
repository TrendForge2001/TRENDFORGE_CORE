"""Canonical ranking stage for scanner results."""
from __future__ import annotations

from typing import Iterable


class RankingEngine:
    """Rank scan results deterministically by score, confidence and symbol."""

    def rank(self, signals: Iterable) -> list:
        return sorted(
            list(signals),
            key=lambda x: (
                float(getattr(x, "overall_score", getattr(x, "score", 0.0)) or 0.0),
                float(getattr(x, "confidence", 0.0) or 0.0),
                str(getattr(x, "symbol", "")),
            ),
            reverse=True,
        )

    def top_n(self, signals: Iterable, n: int = 20) -> list:
        return self.rank(signals)[: max(0, int(n))]

    def health(self) -> dict:
        return {"status": "healthy", "deterministic": True}
