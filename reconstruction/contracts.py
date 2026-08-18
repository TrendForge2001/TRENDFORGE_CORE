"""Canonical contracts shared by reconstruction and engine layers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StockPayload:
    """Canonical per-symbol payload passed through the TrendForge engines."""

    symbol: str
    df: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    fundamentals: Any = None
    corporate_actions: Any = None
    big_shark: Any = None
    market_regime: Any = None
    sector: Any = None
    risk: Any = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "symbol": self.symbol,
            "df": self.df,
            **self.metadata,
            "fundamentals": self.fundamentals,
            "corporate_actions": self.corporate_actions,
            "big_shark": self.big_shark,
            "market_regime": self.market_regime,
            "sector": self.sector,
            "risk": self.risk,
        }
        payload["data"] = self.df
        return payload


@dataclass(frozen=True, slots=True)
class EnrichmentResult:
    symbol: str
    data: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "data": self.data,
            "warnings": list(self.warnings),
            "failures": list(self.failures),
            "success": self.success,
        }


__all__ = ["StockPayload", "EnrichmentResult"]
