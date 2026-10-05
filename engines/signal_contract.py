"""Structural input contract for the final Signal Engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping
from engines.base_engine import EngineResult

@dataclass(frozen=True)
class SignalInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class SignalInputContract:
    REQUIRED = ("Market Regime Engine", "Technical Engine", "Price Action Engine", "Risk Engine")
    def validate(self, results: Mapping[str, EngineResult] | None) -> SignalInputReport:
        if not isinstance(results, Mapping):
            return SignalInputReport(False, invalid=["engine_results"])
        missing = [name for name in self.REQUIRED if results.get(name) is None]
        invalid = []
        for name, result in results.items():
            if result is None: continue
            try:
                if float(result.max_score or 0) < 0: invalid.append(f"{name}:max_score")
                if float(result.score or 0) < 0: invalid.append(f"{name}:score")
            except (TypeError, ValueError):
                invalid.append(f"{name}:numeric_score")
        warnings = []
        if missing: warnings.append("Required signal components are unavailable; final signal is not safe to generate")
        return SignalInputReport(not missing and not invalid, missing, invalid, warnings)

__all__=["SignalInputContract","SignalInputReport"]
