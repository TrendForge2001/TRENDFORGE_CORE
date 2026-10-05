"""Canonical market-regime engine facade.

The scanner pipeline owns indicator calculation. This facade keeps the
existing MarketRegimeEngine scoring/regime logic while making its indicator
calculation dependency a pass-through operation.
"""
from __future__ import annotations

import pandas as pd

from engines.market_regime_engine import MarketRegimeEngine


class _CanonicalIndicators:
    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        return df


class CanonicalMarketRegimeEngine(MarketRegimeEngine):
    """Consume the pipeline's enriched indicator dataframe."""

    def __init__(self) -> None:
        super().__init__(indicator_engine=_CanonicalIndicators())


__all__ = ["CanonicalMarketRegimeEngine"]
