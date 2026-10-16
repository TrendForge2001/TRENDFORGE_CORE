from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd

from core.database import initialize_database
from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from services.fundamental_completion_service import FundamentalCompletionService
from services.fundamental_coverage_service import FundamentalCoverageService
from services.fundamental_data_manager import FundamentalDataManager


class FakeUniverse:
    def __init__(self, symbols):
        self._members = [
            SimpleNamespace(
                symbol=symbol,
                name=("DUMMY INDEX ROW" if symbol.startswith("DUMMY") else symbol),
            )
            for symbol in symbols
        ]
        self.refresh_calls = []

    def ensure_loaded(self, refresh=False):
        self.refresh_calls.append(bool(refresh))
        return list(self._members)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strong_values():
    return {
        "roce": 30.0,
        "roe": 20.0,
        "sales_growth": 25.0,
        "profit_growth": 25.0,
        "eps_growth": 25.0,
        "debt_equity": 0.2,
        "promoter_holding": 70.0,
        "pledged": 0.0,
    }


def _completion_row(symbol: str) -> dict:
    return {
        "Symbol": symbol,
        "ROCE": 30.0,
        "ROE": 20.0,
        "Sales Growth": 25.0,
        "Profit Growth": 25.0,
        "EPS Growth": 25.0,
        "Debt/Equity": 0.2,
        "Promoter Holding": 70.0,
        "Pledged %": 0.0,
        "Completion Source Type": "SCREENER",
        "Completion Source": "screener",
        "Completion Source Ref": "https://example.test/fundamentals",
        "Completion As Of": "2026-09-30",
        "ROE Period": "FY2026",
        "EPS Growth Status": "VALID",
        "EPS Growth Method": "3Y_CAGR",
        "EPS Start Period": "FY2023",
        "EPS End Period": "FY2026",
        "Promoter Holding As Of": "2026-09-30",
        "Pledged As Of": "2026-09-30",
    }


def test_coverage_includes_missing_universe_symbols_and_excludes_placeholder(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(
        db_path=str(db_path),
        max_age_days=365,
    )
    manager.upsert(
        "AAA",
        _strong_values(),
        source="curated",
        as_of=_now(),
    )
    manager.upsert(
        "BBB",
        {"roce": 22.0},
        source="partial",
        as_of=_now(),
    )
    universe = FakeUniverse(["AAA", "BBB", "CCC", "DUMMYHEG"])

    service = FundamentalCoverageService(
        manager=manager,
        universe=universe,
    )
    report = service.report()

    assert report["version"] == "R69.4"
    assert report["tradable_symbols"] == 3
    assert report["database_records"] == 2
    assert report["missing_database_records"] == 1
    assert report["database_coverage_pct"] == 66.67
    assert report["readiness_counts"]["READY_PASS"] == 1
    assert report["readiness_counts"]["DATA_INCOMPLETE"] == 1
    assert report["readiness_counts"]["MISSING"] == 1
    assert report["scoring_ready_records"] == 1
    assert report["scoring_readiness_pct"] == 33.33
    assert report["field_coverage"]["roce"]["present"] == 2
    assert report["field_coverage"]["roe"]["present"] == 1
    assert report["field_coverage"]["roe"]["missing"] == 2

    by_symbol = {row["symbol"]: row for row in report["records"]}
    assert set(by_symbol) == {"AAA", "BBB", "CCC"}
    assert by_symbol["CCC"]["status"] == "MISSING"
    assert by_symbol["CCC"]["completeness_pct"] == 0.0
    assert by_symbol["BBB"]["missing"]
    assert "DUMMYHEG" not in by_symbol

    service.close()


def test_incomplete_only_keeps_missing_and_incomplete_not_quality_ready(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=365)
    manager.upsert("AAA", _strong_values(), source="curated", as_of=_now())
    manager.upsert("BBB", {"roce": 20.0}, source="partial", as_of=_now())

    report = FundamentalCoverageService(
        manager=manager,
        universe=FakeUniverse(["AAA", "BBB", "CCC"]),
    ).report(incomplete_only=True)

    assert [row["symbol"] for row in report["records"]] == ["BBB", "CCC"]
    assert report["readiness_counts"]["READY_PASS"] == 1
    assert report["scoring_ready_records"] == 1


def test_completion_export_includes_unseeded_nifty500_member(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=365)
    manager.upsert("AAA", _strong_values(), source="curated", as_of=_now())
    manager.upsert("BBB", {"roce": 20.0}, source="partial", as_of=_now())

    service = FundamentalCompletionService(
        manager=manager,
        universe=FakeUniverse(["AAA", "BBB", "CCC", "DUMMYHEG"]),
    )
    frame = service.completion_frame()

    assert list(frame["Symbol"]) == ["BBB", "CCC"]
    ccc = frame[frame["Symbol"] == "CCC"].iloc[0]
    assert ccc["Current Completeness %"] == 0.0
    assert bool(ccc["Database Record"]) is False
    assert "roe" in str(ccc["Missing Fields"])
    assert "DUMMYHEG" not in set(frame["Symbol"])


def test_completion_can_create_missing_database_row_only_for_universe_member(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=365)
    universe = FakeUniverse(["AAA", "CCC"])
    service = FundamentalCompletionService(
        manager=manager,
        universe=universe,
    )

    completion = tmp_path / "completion.csv"
    pd.DataFrame([_completion_row("CCC")]).to_csv(completion, index=False)

    preview = service.process_file(completion, apply=False)
    assert preview["eligible"] == 1
    assert preview["unknown_symbols"] == 0
    assert preview["rows"][0]["created_database_record"] is True
    assert manager.inspect("CCC") is None

    applied = service.process_file(completion, apply=True)
    assert applied["applied_records"] == 1
    assert applied["applied_fields"] == 8
    assert applied["evidence_records"] == 8
    assert applied["completed_records"] == 1

    inspected = manager.inspect("CCC")
    assert inspected is not None
    assert inspected["quality"]["completeness_pct"] == 100.0
    assert inspected["quality"]["contract_ready"] is True
    assert inspected["metadata"]["source"] == "fundamental_completion"
    assert inspected["metadata"]["source_file"] == "completion.csv"


def test_completion_still_rejects_symbol_outside_nifty500(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path))
    service = FundamentalCompletionService(
        manager=manager,
        universe=FakeUniverse(["AAA", "BBB"]),
    )

    completion = tmp_path / "outside.csv"
    pd.DataFrame([_completion_row("ZZZ")]).to_csv(completion, index=False)

    report = service.process_file(completion, apply=True)

    assert report["unknown_symbols"] == 1
    assert report["applied_records"] == 0
    assert manager.inspect("ZZZ") is None


def test_nm_evidence_counts_as_scoring_ready(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    manager = FundamentalDataManager(db_path=str(db_path), max_age_days=365)
    values = _strong_values()
    values.pop("eps_growth")
    manager.upsert("NMCO", values, source="curated", as_of=_now())

    evidence = FundamentalFieldEvidenceRepository(db_path=str(db_path))
    evidence.add_many(
        [
            {
                "symbol": "NMCO",
                "field": "eps_growth",
                "value": None,
                "value_status": "N/M",
                "period_type": "CAGR",
                "period_label": "FY2023-FY2026",
                "period_start": "FY2023",
                "period_end": "FY2026",
                "methodology": "3Y_CAGR",
                "source_type": "SCREENER",
                "source": "screener",
                "source_ref": "https://example.test/nmco",
                "as_of": "2026-09-30",
                "reason": "NEGATIVE_BASE",
                "source_file": "nm.csv",
            }
        ]
    )

    service = FundamentalCoverageService(
        manager=manager,
        universe=FakeUniverse(["NMCO"]),
        evidence_repository=evidence,
    )
    report = service.report()

    row = report["records"][0]
    assert row["status"] == "NM_READY"
    assert row["scoring_eligible"] is True
    assert row["excluded_fields"] == ["eps_growth"]
    assert report["scoring_ready_records"] == 1
    assert report["scoring_readiness_pct"] == 100.0

    evidence.close()
