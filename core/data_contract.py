"""Canonical market-data contract for TrendForge engine boundaries."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

REQUIRED_OHLCV = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True, slots=True)
class DataContractResult:
    valid: bool
    rows: int
    missing: tuple[str, ...] = ()
    invalid_columns: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "rows": self.rows,
            "missing": list(self.missing),
            "invalid_columns": list(self.invalid_columns),
            "reasons": list(self.reasons),
        }


class MarketDataContract:
    required = REQUIRED_OHLCV

    @classmethod
    def validate(cls, df: Any) -> DataContractResult:
        if not isinstance(df, pd.DataFrame):
            return DataContractResult(False, 0, reasons=("dataframe_required",))
        rows = len(df)
        if rows == 0:
            return DataContractResult(False, 0, reasons=("dataframe_empty",))

        missing = tuple(c for c in cls.required if c not in df.columns)
        if missing:
            return DataContractResult(
                False, rows, missing=missing,
                reasons=("required_ohlcv_columns_missing",),
            )

        invalid: list[str] = []
        numeric: dict[str, pd.Series] = {}
        for column in cls.required:
            converted = pd.to_numeric(df[column], errors="coerce")
            numeric[column] = converted
            if not pd.api.types.is_numeric_dtype(df[column]) or not converted.notna().all():
                invalid.append(column)

        if invalid:
            return DataContractResult(
                False, rows, invalid_columns=tuple(invalid),
                reasons=("ohlcv_columns_must_be_finite_numeric",),
            )

        reasons: list[str] = []
        if (numeric["high"] < numeric["low"]).any():
            reasons.append("high_below_low_detected")
        if (numeric["close"] > numeric["high"]).any() or (numeric["close"] < numeric["low"]).any():
            reasons.append("close_outside_high_low_range")
        if (numeric["open"] > numeric["high"]).any() or (numeric["open"] < numeric["low"]).any():
            reasons.append("open_outside_high_low_range")
        if (numeric["volume"] < 0).any():
            reasons.append("negative_volume_detected")

        return DataContractResult(
            not reasons, rows, reasons=tuple(reasons)
        )

    @classmethod
    def assert_valid(cls, df: Any) -> None:
        result = cls.validate(df)
        if not result.valid:
            raise ValueError(", ".join(result.reasons or ("invalid_market_data",)))


__all__ = ["DataContractResult", "MarketDataContract", "REQUIRED_OHLCV"]
