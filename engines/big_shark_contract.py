"""Input contract for institutional / Big Shark analysis."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True)
class BigSharkInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class BigSharkInputContract:
    """Validate supplied institutional/shareholding data without fabricating it."""
    def validate(self, stock: Mapping[str, Any] | None) -> BigSharkInputReport:
        if not isinstance(stock, Mapping):
            return BigSharkInputReport(False, invalid=["stock_payload"])
        fields = ("shareholding", "shareholding_snapshot", "institutional_activity", "institutional_holders", "holding_changes", "block_deals", "bulk_deals", "deals", "promoter")
        supplied = [f for f in fields if stock.get(f) not in (None, "", [], {})]
        if not supplied:
            return BigSharkInputReport(True, warnings=["Institutional/shareholding data unavailable; score must remain low-confidence."])
        invalid = []
        for field in supplied:
            value = stock[field]
            if isinstance(value, (str, bytes, int, float)) and field not in {"promoter"}:
                invalid.append(field)
        return BigSharkInputReport(not invalid, invalid=invalid)

__all__ = ["BigSharkInputContract", "BigSharkInputReport"]
