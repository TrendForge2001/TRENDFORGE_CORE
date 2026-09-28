"""Canonical Technical Engine facade."""
from __future__ import annotations

from engines.technical_engine import TechnicalEngine


class CanonicalTechnicalEngine(TechnicalEngine):
    """Use the canonical TechnicalEngine without recalculating indicators."""

    def evaluate(self, stock):
        return super().evaluate(stock)


__all__ = ["CanonicalTechnicalEngine"]
