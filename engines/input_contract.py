"""Engine-facing input contract and fail-closed validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

ENGINE_FIELDS = ("fundamentals", "corporate_actions", "big_shark", "market_regime", "sector", "risk", "df")

@dataclass(frozen=True, slots=True)
class EngineInputReport:
    ready: bool
    missing: tuple[str, ...] = ()
    invalid: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class EngineInputContract:
    """Validate structural inputs without fabricating unavailable enrichment data."""
    def validate(self, payload: Mapping[str, Any]) -> EngineInputReport:
        missing, invalid, warnings = [], [], []
        if not str(payload.get("symbol", "")).strip(): missing.append("symbol")
        if payload.get("df") is None: missing.append("df")
        elif not hasattr(payload["df"], "columns"): invalid.append("df")
        for field in ENGINE_FIELDS:
            if field not in payload: warnings.append(f"optional_or_unavailable:{field}")
        return EngineInputReport(not missing and not invalid, tuple(missing), tuple(invalid), tuple(warnings))

__all__ = ["ENGINE_FIELDS", "EngineInputContract", "EngineInputReport"]
