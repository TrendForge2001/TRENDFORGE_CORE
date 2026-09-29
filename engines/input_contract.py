"""Global input contract for the canonical TrendForge engine pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import pandas as pd


class _ContractItems(tuple):
    def __eq__(self, other):
        if isinstance(other, (list, tuple)):
            return tuple(self) == tuple(other)
        return NotImplemented


@dataclass(frozen=True)
class EngineInputReport:
    ready: bool
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "missing": list(self.missing),
            "invalid": list(self.invalid),
            "warnings": list(self.warnings),
        }


class EngineInputContract:
    """Validate only global prerequisites; engine-specific contracts remain authoritative."""

    REQUIRED = ("symbol", "df")

    def validate(self, stock: Mapping[str, Any] | None) -> EngineInputReport:
        if not isinstance(stock, Mapping):
            return EngineInputReport(False, invalid=["stock_payload"])

        missing: list[str] = []
        invalid: list[str] = []
        warnings: list[str] = []

        symbol = stock.get("symbol") or stock.get("ticker") or stock.get("tradingsymbol")
        if not symbol or not str(symbol).strip():
            missing.append("symbol")

        frame = next(
            (stock.get(key) for key in ("df", "data", "ohlcv", "candles", "history")
             if isinstance(stock.get(key), pd.DataFrame)),
            None,
        )
        if frame is None:
            missing.append("df")
        elif frame.empty:
            invalid.append("df_empty")
        elif "close" not in frame.columns:
            invalid.append("df_close_column")
        elif pd.to_numeric(frame["close"], errors="coerce").dropna().empty:
            invalid.append("df_close_values")

        if frame is not None and not frame.empty and len(frame) < 200:
            warnings.append("Less than 200 candles; long-horizon engine context may be limited")

        return EngineInputReport(not missing and not invalid, _ContractItems(missing), _ContractItems(invalid), _ContractItems(warnings))


__all__ = ["EngineInputContract", "EngineInputReport"]
