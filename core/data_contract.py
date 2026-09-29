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
    """Validate the minimum canonical OHLCV payload before engine execution."""

    required = REQUIRED_OHLCV

    @classmethod
    def validate(cls, df: Any) -> DataContractResult:
        if not isinstance(df, pd.DataFrame):
            return DataContractResult(valid=False, rows=0, reasons=("dataframe_required",))
        rows = len(df)
        if rows == 0:
            return DataContractResult(valid=False, rows=0, reasons=("dataframe_empty",))
        missing = tuple(column for column in cls.required if column not in df.columns)
        if missing:
            return DataContractResult(valid=False, rows=rows, missing=missing,
                                      reasons=("required_ohlcv_columns_missing",))

        invalid: list[str] = []
        reasons: list[str] = []
        for column in cls.required:
            if not pd.api.types.is_numeric_dtype(df[column]):
                invalid.append(column)
                continue
            finite = pd.to_numeric(df[column], errors="coerce").replace([float("inf"), float("-inf")], pd.NA).notna().all()
            if not finite:
                invalid.append(column)
        if invalid:
            reasons.append("ohlcv_columns_must_be_finite_numeric")
            return DataContractResult(valid=False, rows=rows, missing=missing,
                                      invalid_columns=tuple(invalid), reasons=tuple(reasons))
        if (df["high"] < df["low"]).any():
            reasons.append("high_below_low_detected")
        if (df["close"] > df["high"]).any() or (df["close"] < df["low"]).any():
            reasons.append("close_outside_high_low_range")
        if (df["open"] > df["high"]).any() or (df["open"] < df["low"]).any():
            reasons.append("open_outside_high_low_range")
        if (df["volume"] < 0).any():
            reasons.append("negative_volume_detected")

        return DataContractResult(valid=not missing and not invalid and not reasons,
                                  rows=rows, missing=missing,
                                  invalid_columns=tuple(invalid), reasons=tuple(reasons))

    @classmethod
    def assert_valid(cls, df: Any) -> None:
        result = cls.validate(df)
        if not result.valid:
            if "dataframe_empty" in result.reasons:
                raise ValueError("No candle data")
            if "required_ohlcv_columns_missing" in result.reasons:
                raise ValueError("incomplete OHLCV data")
            details = ", ".join(result.reasons or ("invalid_market_data",))
            raise ValueError(details)


__all__ = ["DataContractResult", "MarketDataContract", "REQUIRED_OHLCV"]
