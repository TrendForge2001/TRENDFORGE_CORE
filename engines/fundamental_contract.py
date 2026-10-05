"""Input contract for the Fundamental Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class FundamentalInputReport:
    ready: bool
    missing: list[str] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"ready": self.ready, "missing": list(self.missing),
                "invalid": list(self.invalid), "warnings": list(self.warnings)}


class FundamentalInputContract:
    """Validate the minimum fields required for a meaningful fundamental score."""

    REQUIRED = ("roce", "roe", "sales_growth", "profit_growth", "eps_growth",
                "debt_equity", "promoter_holding", "pledged")

    def validate(self, stock: Mapping[str, Any] | None) -> FundamentalInputReport:
        if not isinstance(stock, Mapping):
            return FundamentalInputReport(False, invalid=["stock_payload"])
        missing: list[str] = []
        invalid: list[str] = []
        warnings: list[str] = []
        for field in self.REQUIRED:
            if field not in stock or stock[field] is None:
                missing.append(field)
                continue
            try:
                value = float(stock[field])
                if field == "pledged" and not 0 <= value <= 100:
                    invalid.append(field)
                elif field == "promoter_holding" and not 0 <= value <= 100:
                    invalid.append(field)
                elif field in {"roce", "roe", "sales_growth", "profit_growth", "eps_growth"} and not -1000 <= value <= 1000:
                    invalid.append(field)
                elif field == "debt_equity" and value < 0:
                    invalid.append(field)
            except (TypeError, ValueError):
                invalid.append(field)
        if "pledged" not in missing and "pledged" not in invalid and float(stock["pledged"]) > 10:
            warnings.append("High promoter pledge")
        if "debt_equity" not in missing and "debt_equity" not in invalid and float(stock["debt_equity"]) > 2:
            warnings.append("High debt-to-equity")
        return FundamentalInputReport(not missing and not invalid, missing, invalid, warnings)


__all__ = ["FundamentalInputContract", "FundamentalInputReport"]
