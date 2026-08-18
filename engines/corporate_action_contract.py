"""Input contract for the Corporate Action & Event Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class CorporateActionInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing), "invalid": list(self.invalid), "warnings": list(self.warnings)}


class CorporateActionInputContract:
    """Validate event payload structure without treating missing event data as a fake negative event."""

    EVENT_KEYS = ("corporate_actions", "corporate_events", "events", "corporate_action")
    SYMBOL_KEYS = ("symbol", "ticker", "tradingsymbol")

    def validate(self, stock: Mapping[str, Any] | None) -> CorporateActionInputReport:
        if not isinstance(stock, Mapping):
            return CorporateActionInputReport(False, invalid=["stock_payload"])

        missing: list[str] = []
        invalid: list[str] = []
        warnings: list[str] = []

        if not any(stock.get(key) for key in self.SYMBOL_KEYS):
            missing.append("symbol")

        supplied = False
        for key in self.EVENT_KEYS:
            if key not in stock or stock[key] is None:
                continue
            supplied = True
            value = stock[key]
            if isinstance(value, Mapping):
                continue
            if not isinstance(value, (list, tuple, set)):
                invalid.append(key)
                continue
            for index, event in enumerate(value):
                if not isinstance(event, Mapping) and not hasattr(event, "__dict__"):
                    invalid.append(f"{key}[{index}]")

        if not supplied:
            warnings.append("No inline corporate-event data; provider/repository discovery may supply events.")

        return CorporateActionInputReport(not missing and not invalid, missing, invalid, warnings)


__all__ = ["CorporateActionInputContract", "CorporateActionInputReport"]
