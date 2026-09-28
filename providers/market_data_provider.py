"""Canonical market-data provider contract used by scanner pipelines."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class MarketDataProvider(ABC):
    @abstractmethod
    def candles(self, symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
        raise NotImplementedError

    def live_price(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError

    def health(self) -> dict[str, Any]:
        return {"status": "unknown", "provider": self.__class__.__name__}


__all__ = ["MarketDataProvider"]
