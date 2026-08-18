"""Pre-flight data readiness checks for the canonical TrendForge engines."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    """Validate required stock payload inputs without coupling to providers."""

    CORE_KEYS = ("symbol", "df")
    OPTIONAL_KEYS = (
        "fundamentals",
        "corporate_actions",
        "big_shark",
        "market_regime",
        "sector",
        "risk",
    )

    def check(self, stock: dict[str, Any]) -> EngineDataReadiness:
        missing: list[str] = []
        warnings: list[str] = []
        available: list[str] = []

        for key in self.CORE_KEYS:
            value = stock.get(key)
            if value is None or (key == "df" and getattr(value, "empty", False)):
                missing.append(key)
            else:
                available.append(key)

        for key in self.OPTIONAL_KEYS:
            value = stock.get(key)
            if value is None:
                warnings.append(f"optional_data_missing:{key}")
            else:
                available.append(key)

        if missing:
            reasons = tuple(f"required_data_missing:{key}" for key in missing)
        else:
            reasons = ()

        return EngineDataReadiness(
            ready=not missing,
            available=tuple(available),
            missing=tuple(missing),
            warnings=tuple(warnings),
            reasons=reasons,
        )


__all__ = ["EngineDataReadiness", "EngineDataReadinessChecker"]
