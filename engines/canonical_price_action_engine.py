"""Canonical price-action engine facade.

The canonical pipeline owns indicator calculation. This facade preserves the
existing PriceActionEngine scoring logic while making its indicator dependency
an identity/pass-through operation on an already enriched dataframe.
"""
from __future__ import annotations

import pandas as pd

from engines.price_action_engine import PriceActionEngine


class _CanonicalIndicators:
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        return df


class CanonicalPriceActionEngine(PriceActionEngine):
    """Consume the pipeline's indicator frame without recalculating it."""

    def __init__(self) -> None:
        super().__init__(indicator_engine=_CanonicalIndicators())


__all__ = ["CanonicalPriceActionEngine"]
