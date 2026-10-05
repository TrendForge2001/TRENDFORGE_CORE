"""Input contract for the Sector Engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True)
class SectorInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class SectorInputContract:
    """Validate supplied sector snapshots without inventing unavailable data."""
    def validate(self, stock: Mapping[str, Any] | None) -> SectorInputReport:
        if not isinstance(stock, Mapping):
            return SectorInputReport(False, invalid=["stock_payload"])
        snapshot = next((stock.get(k) for k in ("sector_snapshot", "sector_data") if isinstance(stock.get(k), Mapping)), None)
        sector = stock.get("sector_name") or stock.get("sector") or stock.get("industry")
        if snapshot is None and not sector:
            return SectorInputReport(True, warnings=["Sector data unavailable; engine may use provider/repository fallback"])
        if snapshot is None:
            return SectorInputReport(True, warnings=["Sector snapshot unavailable; engine will use provider/repository fallback"])
        numeric = ("change_1d", "change_1w", "change_1m", "change_3m", "volume_ratio", "relative_strength", "advancing", "declining", "fii_flow", "dii_flow", "leadership_score")
        invalid = []
        for key in numeric:
            if key in snapshot and snapshot[key] is not None:
                try: float(snapshot[key])
                except (TypeError, ValueError): invalid.append(key)
        return SectorInputReport(not invalid, invalid=invalid)

__all__ = ["SectorInputContract", "SectorInputReport"]
