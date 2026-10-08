from __future__ import annotations

import json

import pytest

from core.database import initialize_database
from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamental_field_update_repository import (
    FundamentalFieldUpdateRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from services.fundamental_bootstrap_service import FundamentalBootstrapService


def _seed(path):
    initialize_database(str(path))
    fundamentals = FundamentalsRepository(db_path=str(path))
    evidence = FundamentalFieldEvidenceRepository(db=fundamentals.db)
    updates = FundamentalFieldUpdateRepository(db=fundamentals.db)
    fundamentals.save({
        "symbol": "GVT&D",
        "roce": 30.0,
        "roe": 57.0,
        "sales_growth": 25.0,
        "profit_growth": 25.0,
        "debt_to_equity": 0.2,
        "promoter_holding": 51.0,
        "pledged": 0.0,
        "source": "test",
        "as_of": "2026-07-07",
    })
    evidence.add_many([{
        "symbol": "GVT&D",
        "field": "eps_growth",
        "value": None,
        "value_status": "N/M",
        "period_type": "CAGR",
        "period_start": "FY2023",
        "period_end": "FY2026",
        "methodology": "3Y_CAGR",
        "source_type": "SCREENER",
        "source": "Screener",
        "source_ref": "https://example.test/gvtd",
        "as_of": "2026-03-31",
        "reason": "NEGATIVE_BASE",
    }])
    updates.add_many([{
        "symbol": "GVT&D",
        "field": "roe",
        "value": 57.0,
        "source": "Screener",
        "as_of": "2026-03-31",
    }])
    fundamentals.close()


def test_export_verify_and_empty_only_restore(tmp_path):
    source_db = tmp_path / "source.db"
    _seed(source_db)
    bundle = tmp_path / "bootstrap.json"

    source = FundamentalBootstrapService(db_path=str(source_db))
    exported = source.export_bundle(bundle)
    source.close()

    assert exported["fundamental_records"] == 1
    assert exported["evidence_records"] == 1
    assert exported["field_update_records"] == 1

    target_db = tmp_path / "target.db"
    initialize_database(str(target_db))
    target = FundamentalBootstrapService(db_path=str(target_db))
    applied = target.apply_bundle(
        bundle,
        expected_file_sha256=exported["file_sha256"],
    )
    assert applied["status"] == "applied"
    assert applied["database_records"] == 1
    assert target.fundamentals.by_symbol("GVT&D")["roe"] == 57.0
    assert target.evidence.latest_by_field("GVT&D")["eps_growth"][
        "value_status"
    ] == "N/M"

    skipped = target.apply_bundle(
        tmp_path / "missing.json",
        expected_file_sha256="0" * 64,
    )
    assert skipped["status"] == "skipped_nonempty"
    target.close()


def test_tampered_bundle_is_rejected(tmp_path):
    db = tmp_path / "source.db"
    _seed(db)
    bundle = tmp_path / "bootstrap.json"
    service = FundamentalBootstrapService(db_path=str(db))
    service.export_bundle(bundle)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    data["fundamentals"][0]["roe"] = 1.0
    bundle.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="payload SHA256"):
        service.verify_bundle(bundle, require_pinned_sha256=False)
    service.close()


def test_wrong_pinned_file_hash_is_rejected(tmp_path):
    db = tmp_path / "source.db"
    _seed(db)
    bundle = tmp_path / "bootstrap.json"
    service = FundamentalBootstrapService(db_path=str(db))
    service.export_bundle(bundle)
    with pytest.raises(ValueError, match="file SHA256"):
        service.verify_bundle(
            bundle,
            expected_file_sha256="0" * 64,
        )
    service.close()
