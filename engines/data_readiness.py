"""Pre-flight data readiness checks for the canonical TrendForge engines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EngineDataReadiness:
    ready: bool
    available: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "available": list(self.available),
            "missing": list(self.missing),
            "warnings": list(self.warnings),
            "reasons": list(self.reasons),
        }


class EngineDataReadinessChecker:
    """Validate required payload inputs without coupling engines to providers."""

    CORE_KEYS = ("symbol", "df")
    OPTIONAL_KEYS = (
        "fundamentals", "corporate_actions", "big_shark",
        "market_regime", "sector", "risk",
    )

    def check(self, stock: dict[str, Any] | None) -> EngineDataReadiness:
        stock = stock or {}
        missing: list[str] = []
        warnings: list[str] = []
        available: list[str] = []

        for key in self.CORE_KEYS:
            value = stock.get(key)
            if value is None or (key == "symbol" and not str(value).strip()):
                missing.append(key)
            elif key == "df" and getattr(value, "empty", False):
                missing.append(key)
            else:
                available.append(key)

        for key in self.OPTIONAL_KEYS:
            if stock.get(key) is None:
                warnings.append(f"optional_data_missing:{key}")
            else:
                available.append(key)

        reasons = tuple(f"required_data_missing:{key}" for key in missing)
        return EngineDataReadiness(
            ready=not missing,
            available=tuple(available),
            missing=tuple(missing),
            warnings=tuple(warnings),
            reasons=reasons,
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "healthy",
            "core_keys": list(self.CORE_KEYS),
            "optional_keys": list(self.OPTIONAL_KEYS),
        }


__all__ = ["EngineDataReadiness", "EngineDataReadinessChecker"]
