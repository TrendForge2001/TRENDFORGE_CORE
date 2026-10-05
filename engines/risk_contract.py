"""Structural input contract for the Risk Engine."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True)
class RiskInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}

class RiskInputContract:
    """Fail closed when entry, ATR, or capital inputs cannot support risk sizing."""
    def validate(self, stock: Mapping[str, Any] | None) -> RiskInputReport:
        if not isinstance(stock, Mapping):
            return RiskInputReport(False, invalid=["stock_payload"])
        snapshot = stock.get("snapshot", stock)
        def num(key: str):
            value = snapshot.get(key) if isinstance(snapshot, Mapping) else getattr(snapshot, key, None)
            try: return float(value)
            except (TypeError, ValueError): return None
        missing=[]; invalid=[]; warnings=[]
        close = num("close"); atr = num("atr")
        if close is None: missing.append("close")
        elif close <= 0: invalid.append("close_positive")
        if atr is None: missing.append("atr")
        elif atr <= 0: invalid.append("atr_positive")
        capital = stock.get("capital", 0)
        try: capital=float(capital)
        except (TypeError, ValueError): capital=None
        if capital is None: invalid.append("capital_numeric")
        elif capital <= 0: warnings.append("Capital is zero/non-positive; position sizing cannot produce a usable quantity")
        return RiskInputReport(not missing and not invalid, missing, invalid, warnings)

__all__=["RiskInputContract","RiskInputReport"]
