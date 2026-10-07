"""N/M-aware readiness classification for fundamental scoring."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from engines.fundamental_contract import (
    FundamentalInputContract,
    FundamentalInputReport,
)


@dataclass(frozen=True)
class FundamentalScoringReadiness:
    state: str
    eligible: bool
    excluded_fields: tuple[str, ...] = ()
    data_confidence_pct: float = 0.0
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    strict_report: FundamentalInputReport | None = field(default=None)

    NUMERIC_READY = "NUMERIC_READY"
    EVIDENCE_COMPLETE_NM = "EVIDENCE_COMPLETE_NM"
    INCOMPLETE = "INCOMPLETE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "eligible": self.eligible,
            "excluded_fields": list(self.excluded_fields),
            "data_confidence_pct": self.data_confidence_pct,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "strict_report": (
                self.strict_report.as_dict()
                if self.strict_report is not None
                else None
            ),
        }


class FundamentalScoringReadinessResolver:
    """Classify whether strict or evidence-backed N/M scoring is allowed."""

    NM_SCORABLE_FIELDS = {"eps_growth"}
    NM_SCORABLE_REASONS = {"NEGATIVE_BASE", "ZERO_BASE"}
    FY_PATTERN = re.compile(r"^FY(\d{4})$")

    def __init__(
        self,
        input_contract: FundamentalInputContract | None = None,
    ) -> None:
        self.input_contract = input_contract or FundamentalInputContract()

    @staticmethod
    def _mapping(value: Any) -> Mapping[str, Any]:
        return value if isinstance(value, Mapping) else {}

    @classmethod
    def _field_evidence(
        cls,
        stock: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        quality = cls._mapping(stock.get("fundamental_data_quality"))
        evidence = cls._mapping(quality.get("field_evidence"))
        if evidence:
            return evidence

        fundamentals = cls._mapping(stock.get("fundamentals"))
        meta = cls._mapping(fundamentals.get("_meta"))
        return cls._mapping(meta.get("field_evidence"))

    @classmethod
    def _valid_three_year_period(cls, evidence: Mapping[str, Any]) -> bool:
        start = str(evidence.get("period_start") or "").strip().upper()
        end = str(evidence.get("period_end") or "").strip().upper()
        start_match = cls.FY_PATTERN.fullmatch(start)
        end_match = cls.FY_PATTERN.fullmatch(end)
        if not start_match or not end_match:
            return False
        return int(end_match.group(1)) - int(start_match.group(1)) == 3

    @classmethod
    def _valid_nm_evidence(
        cls,
        field_name: str,
        evidence: Mapping[str, Any],
    ) -> tuple[bool, tuple[str, ...]]:
        errors: list[str] = []
        if field_name not in cls.NM_SCORABLE_FIELDS:
            errors.append(f"{field_name}: N/M scoring is not supported")
            return False, tuple(errors)

        status = str(evidence.get("value_status") or "").strip().upper()
        if status != "N/M":
            errors.append(f"{field_name}: evidence status must be N/M")

        if evidence.get("value") is not None:
            errors.append(f"{field_name}: N/M evidence must not contain a numeric value")

        methodology = str(evidence.get("methodology") or "").strip().upper()
        if methodology != "3Y_CAGR":
            errors.append(f"{field_name}: methodology must be 3Y_CAGR")

        period_type = str(evidence.get("period_type") or "").strip().upper()
        if period_type != "CAGR":
            errors.append(f"{field_name}: period type must be CAGR")

        if not cls._valid_three_year_period(evidence):
            errors.append(f"{field_name}: evidence period must span exactly 3 fiscal years")

        reason = str(evidence.get("reason") or "").strip().upper()
        if reason not in cls.NM_SCORABLE_REASONS:
            errors.append(
                f"{field_name}: N/M reason must be NEGATIVE_BASE or ZERO_BASE"
            )

        for key in ("source_type", "source", "source_ref", "as_of"):
            if not str(evidence.get(key) or "").strip():
                errors.append(f"{field_name}: evidence {key} is required")

        return not errors, tuple(errors)

    def assess(
        self,
        stock: Mapping[str, Any] | None,
        *,
        strict_report: FundamentalInputReport | None = None,
    ) -> FundamentalScoringReadiness:
        report = strict_report or self.input_contract.validate(stock)
        if report.ready:
            return FundamentalScoringReadiness(
                state=FundamentalScoringReadiness.NUMERIC_READY,
                eligible=True,
                data_confidence_pct=100.0,
                reasons=("All required numeric fundamental fields are valid",),
                warnings=tuple(report.warnings),
                strict_report=report,
            )

        if not isinstance(stock, Mapping):
            return FundamentalScoringReadiness(
                state=FundamentalScoringReadiness.INCOMPLETE,
                eligible=False,
                data_confidence_pct=0.0,
                reasons=("Fundamental stock payload is invalid",),
                warnings=tuple(report.warnings),
                strict_report=report,
            )

        if report.invalid:
            return FundamentalScoringReadiness(
                state=FundamentalScoringReadiness.INCOMPLETE,
                eligible=False,
                data_confidence_pct=0.0,
                reasons=(
                    "Fundamental input contains invalid numeric fields: "
                    + ", ".join(report.invalid),
                ),
                warnings=tuple(report.warnings),
                strict_report=report,
            )

        missing = tuple(report.missing)
        if missing != ("eps_growth",):
            return FundamentalScoringReadiness(
                state=FundamentalScoringReadiness.INCOMPLETE,
                eligible=False,
                data_confidence_pct=round(
                    (len(self.input_contract.REQUIRED) - len(missing))
                    / len(self.input_contract.REQUIRED)
                    * 100,
                    2,
                ),
                reasons=(
                    "N/M-aware scoring requires eps_growth to be the only missing field",
                ),
                warnings=tuple(report.warnings),
                strict_report=report,
            )

        evidence_map = self._field_evidence(stock)
        evidence = self._mapping(evidence_map.get("eps_growth"))
        valid, errors = self._valid_nm_evidence("eps_growth", evidence)
        if not valid:
            return FundamentalScoringReadiness(
                state=FundamentalScoringReadiness.INCOMPLETE,
                eligible=False,
                data_confidence_pct=87.5,
                reasons=errors or ("Valid N/M EPS-growth evidence is required",),
                warnings=tuple(report.warnings),
                strict_report=report,
            )

        return FundamentalScoringReadiness(
            state=FundamentalScoringReadiness.EVIDENCE_COMPLETE_NM,
            eligible=True,
            excluded_fields=("eps_growth",),
            data_confidence_pct=87.5,
            reasons=(
                "EPS Growth is mathematically non-meaningful and is excluded "
                "using validated N/M evidence",
            ),
            warnings=tuple(report.warnings),
            strict_report=report,
        )


__all__ = [
    "FundamentalScoringReadiness",
    "FundamentalScoringReadinessResolver",
]
