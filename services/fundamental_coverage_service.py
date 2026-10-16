"""NIFTY 500 fundamental coverage and scoring-readiness diagnostics."""
from __future__ import annotations

from collections import Counter
from typing import Any

from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from engines.contracted_fundamental_engine import ContractedFundamentalEngine
from engines.fundamental_scoring_readiness import FundamentalScoringReadiness
from services.fundamental_data_manager import FundamentalDataManager


class FundamentalCoverageService:
    """Measure field coverage and scoring readiness across the tradable universe."""

    VERSION = "R69.4"
    REQUIRED_FIELDS = tuple(FundamentalDataManager.REQUIRED_FIELDS)

    def __init__(
        self,
        *,
        manager: FundamentalDataManager,
        universe: Any,
        evidence_repository: FundamentalFieldEvidenceRepository | None = None,
        engine: ContractedFundamentalEngine | None = None,
    ) -> None:
        if manager is None:
            raise ValueError("manager is required")
        if universe is None:
            raise ValueError("universe is required")
        self.manager = manager
        self.universe = universe
        repository_db = getattr(self.manager.repository, "db", None)
        self.evidence = evidence_repository or FundamentalFieldEvidenceRepository(
            db=repository_db
        )
        self._owns_evidence = evidence_repository is None
        self.engine = engine or ContractedFundamentalEngine()

    @staticmethod
    def _is_placeholder(member: Any) -> bool:
        symbol = str(getattr(member, "symbol", "") or "").strip().upper()
        name = str(getattr(member, "name", "") or "").strip().upper()
        return symbol.startswith("DUMMY") or name.startswith("DUMMY ")

    def _tradable_members(self, *, refresh: bool = False) -> list[Any]:
        members = self.universe.ensure_loaded(refresh=refresh)
        return [
            member
            for member in members
            if not self._is_placeholder(member)
        ]

    def symbols(self, *, refresh: bool = False) -> list[str]:
        return [
            FundamentalsRepository.normalize_symbol(member.symbol)
            for member in self._tradable_members(refresh=refresh)
            if FundamentalsRepository.normalize_symbol(member.symbol)
        ]

    def contains(self, symbol: str, *, refresh: bool = False) -> bool:
        normalized = FundamentalsRepository.normalize_symbol(symbol)
        return bool(normalized) and normalized in set(
            self.symbols(refresh=refresh)
        )

    def _scoring_payload(
        self,
        symbol: str,
        row: dict[str, Any],
    ) -> dict[str, Any]:
        canonical = self.manager._canonical(row)
        try:
            field_evidence = self.evidence.latest_by_field(symbol)
        except Exception:
            field_evidence = {}
        return {
            "symbol": symbol,
            **canonical,
            "fundamental_data_quality": {
                "field_evidence": field_evidence,
            },
        }

    def _row_readiness(
        self,
        symbol: str,
        row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if row is None:
            return {
                "symbol": symbol,
                "status": "MISSING",
                "database_record": False,
                "scoring_eligible": False,
                "quality_pass": False,
                "completeness_pct": 0.0,
                "missing": list(self.REQUIRED_FIELDS),
                "invalid": [],
                "present": [],
                "stale": True,
                "age_days": None,
                "data_confidence_pct": 0.0,
                "scoring_state": None,
                "excluded_fields": [],
            }

        quality = self.manager.quality(row)
        payload = self._scoring_payload(symbol, row)
        scoring = self.engine.readiness_resolver.assess(payload)
        engine_result = self.engine.evaluate(payload)

        if scoring.state == FundamentalScoringReadiness.EVIDENCE_COMPLETE_NM:
            status = "NM_READY"
        elif scoring.state == FundamentalScoringReadiness.NUMERIC_READY:
            status = (
                "READY_PASS"
                if bool(engine_result.passed)
                else "READY_FAIL_QUALITY"
            )
        elif scoring.strict_report is not None and scoring.strict_report.invalid:
            status = "INVALID"
        else:
            status = "DATA_INCOMPLETE"

        return {
            "symbol": symbol,
            "status": status,
            "database_record": True,
            "scoring_eligible": bool(scoring.eligible),
            "quality_pass": bool(engine_result.passed),
            "completeness_pct": quality["completeness_pct"],
            "missing": list(quality["missing"]),
            "invalid": list(quality["invalid"]),
            "present": list(quality["present"]),
            "stale": bool(quality["stale"]),
            "age_days": quality["age_days"],
            "data_confidence_pct": float(scoring.data_confidence_pct),
            "scoring_state": scoring.state,
            "excluded_fields": list(scoring.excluded_fields),
        }

    def report(
        self,
        *,
        refresh_universe: bool = False,
        incomplete_only: bool = False,
        limit: int = 5000,
    ) -> dict[str, Any]:
        symbols = self.symbols(refresh=refresh_universe)
        rows: list[dict[str, Any]] = []
        field_present = Counter({field: 0 for field in self.REQUIRED_FIELDS})
        field_missing = Counter({field: 0 for field in self.REQUIRED_FIELDS})
        field_invalid = Counter({field: 0 for field in self.REQUIRED_FIELDS})
        status_counts: Counter[str] = Counter()

        for symbol in symbols:
            db_row = self.manager.repository.by_symbol(symbol)
            readiness = self._row_readiness(symbol, db_row)
            status_counts[readiness["status"]] += 1

            present = set(readiness["present"])
            missing = set(readiness["missing"])
            invalid = set(readiness["invalid"])
            for field in self.REQUIRED_FIELDS:
                if field in invalid:
                    field_invalid[field] += 1
                elif field in present and field not in missing:
                    field_present[field] += 1
                else:
                    field_missing[field] += 1

            if incomplete_only and readiness["status"] in {
                "READY_PASS",
                "READY_FAIL_QUALITY",
                "NM_READY",
            }:
                continue
            rows.append(readiness)

        total = len(symbols)
        database_records = sum(
            1 for symbol in symbols
            if self.manager.repository.by_symbol(symbol) is not None
        )
        scoring_ready = (
            status_counts["READY_PASS"]
            + status_counts["READY_FAIL_QUALITY"]
            + status_counts["NM_READY"]
        )
        execution_quality_ready = (
            status_counts["READY_PASS"]
            + sum(
                1
                for row in rows
                if row["status"] == "NM_READY" and row["quality_pass"]
            )
        )

        field_coverage = {}
        for field in self.REQUIRED_FIELDS:
            present = int(field_present[field])
            field_coverage[field] = {
                "present": present,
                "missing": int(field_missing[field]),
                "invalid": int(field_invalid[field]),
                "coverage_pct": (
                    round(present * 100.0 / total, 2)
                    if total
                    else 0.0
                ),
            }

        returned = rows[: max(1, min(int(limit), 5000))]
        return {
            "version": self.VERSION,
            "universe": "NIFTY 500",
            "tradable_symbols": total,
            "database_records": database_records,
            "database_coverage_pct": (
                round(database_records * 100.0 / total, 2)
                if total
                else 0.0
            ),
            "scoring_ready_records": scoring_ready,
            "scoring_readiness_pct": (
                round(scoring_ready * 100.0 / total, 2)
                if total
                else 0.0
            ),
            "execution_quality_ready_records": execution_quality_ready,
            "readiness_counts": dict(sorted(status_counts.items())),
            "field_coverage": field_coverage,
            "required_fields": list(self.REQUIRED_FIELDS),
            "returned": len(returned),
            "records": returned,
        }

    def close(self) -> None:
        if self._owns_evidence:
            self.evidence.close()


__all__ = ["FundamentalCoverageService"]
