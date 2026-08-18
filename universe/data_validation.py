"""Market-data eligibility checks used before expensive scanner engines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class DataValidationResult:
    symbol: str
    valid: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)
    rows: int = 0
    avg_volume: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "valid": self.valid,
            "reasons": list(self.reasons),
            "rows": self.rows,
            "avg_volume": self.avg_volume,
        }


class MarketDataValidator:
    """Validate minimum OHLCV quality without imposing a data-provider contract."""

    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def __init__(self, min_rows: int = 200, min_avg_volume: float = 0.0) -> None:
        self.min_rows = max(1, int(min_rows))
        self.min_avg_volume = max(0.0, float(min_avg_volume))

    @staticmethod
    def _column(frame: Any, name: str) -> Any:
        if hasattr(frame, "columns"):
            lookup = {str(c).lower(): c for c in frame.columns}
            return frame[lookup[name]] if name in lookup else None
        return None

    def validate(self, symbol: str, frame: Any) -> DataValidationResult:
        reasons: list[str] = []
        normalized = str(symbol or "").strip().upper()

        if frame is None or not hasattr(frame, "columns"):
            return DataValidationResult(normalized, False, ("missing_ohlcv",))

        missing = [name for name in self.REQUIRED_COLUMNS if self._column(frame, name) is None]
        if missing:
            reasons.append("missing_columns:" + ",".join(missing))

        rows = len(frame.index) if hasattr(frame, "index") else 0
        if rows < self.min_rows:
            reasons.append(f"insufficient_history:{rows}<{self.min_rows}")

        avg_volume = 0.0
        volume = self._column(frame, "volume")
        if volume is not None:
            try:
                values = volume.astype(float)
                avg_volume = float(values.tail(min(rows, 20)).mean()) if rows else 0.0
                if avg_volume < self.min_avg_volume:
                    reasons.append(f"low_liquidity:{avg_volume:.2f}<{self.min_avg_volume:.2f}")
            except (TypeError, ValueError):
                reasons.append("invalid_volume")

        if not reasons:
            try:
                for column in self.REQUIRED_COLUMNS:
                    series = self._column(frame, column)
                    if series.astype(float).isna().all():
                        reasons.append(f"invalid_{column}")
            except (TypeError, ValueError, AttributeError):
                reasons.append("invalid_ohlcv_values")

        return DataValidationResult(
            normalized,
            not reasons,
            tuple(reasons),
            rows,
            avg_volume,
        )

    def validate_many(self, frames: dict[str, Any]) -> tuple[list[str], list[DataValidationResult]]:
        valid: list[str] = []
        rejected: list[DataValidationResult] = []
        for symbol, frame in frames.items():
            result = self.validate(symbol, frame)
            if result.valid:
                valid.append(result.symbol)
            else:
                rejected.append(result)
        return valid, rejected


__all__ = ["DataValidationResult", "MarketDataValidator"]
