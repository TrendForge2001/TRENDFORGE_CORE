"""Structural input contract for the Price Action Engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping
import pandas as pd

@dataclass(frozen=True)
class PriceActionInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class PriceActionInputContract:
    MIN_CANDLES = 30
    REQUIRED_COLUMNS = ("close",)
    def validate(self, stock: Mapping[str, Any] | None) -> PriceActionInputReport:
        if not isinstance(stock, Mapping):
            return PriceActionInputReport(False, invalid=["stock_payload"])
        frame = next((stock.get(k) for k in ("df", "data", "ohlcv", "candles", "history") if isinstance(stock.get(k), pd.DataFrame)), None)
        if frame is None:
            return PriceActionInputReport(False, missing=["ohlcv_dataframe"])
        missing = [c for c in self.REQUIRED_COLUMNS if c not in frame.columns]
        invalid = []
        if len(frame) < self.MIN_CANDLES:
            invalid.append(f"minimum_candles:{self.MIN_CANDLES}")
        if "close" in frame.columns and pd.to_numeric(frame["close"], errors="coerce").dropna().empty:
            invalid.append("close_values")
        warnings = []
        if "volume" not in frame.columns and "Volume" not in frame.columns:
            warnings.append("Volume unavailable; volume-confirmed price action is limited")
        return PriceActionInputReport(not missing and not invalid, missing, invalid, warnings)

__all__ = ["PriceActionInputContract", "PriceActionInputReport"]
