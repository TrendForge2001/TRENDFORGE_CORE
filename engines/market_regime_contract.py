"""Structural input contract for the Market Regime Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd


@dataclass(frozen=True)
class MarketRegimeInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}


class MarketRegimeInputContract:
    """Require sufficient OHLCV history for a regime determination."""

    MIN_CANDLES = 50
    REQUIRED_COLUMNS = ("close",)

    def validate(self, stock: Mapping[str, Any] | None) -> MarketRegimeInputReport:
        if not isinstance(stock, Mapping):
            return MarketRegimeInputReport(False, invalid=["stock_payload"])
        frame = next((stock.get(k) for k in ("df", "data", "ohlcv", "candles", "history") if isinstance(stock.get(k), pd.DataFrame)), None)
        if frame is None:
            return MarketRegimeInputReport(False, missing=["ohlcv_dataframe"])
        missing = [c for c in self.REQUIRED_COLUMNS if c not in frame.columns]
        invalid = []
        if len(frame) < self.MIN_CANDLES:
            invalid.append(f"minimum_candles:{self.MIN_CANDLES}")
        if "close" in frame.columns and frame["close"].dropna().empty:
            invalid.append("close_values")
        warnings = []
        if len(frame) < 200:
            warnings.append("Less than 200 candles; long-term regime context is limited")
        return MarketRegimeInputReport(not missing and not invalid, missing, invalid, warnings)


__all__ = ["MarketRegimeInputContract", "MarketRegimeInputReport"]
