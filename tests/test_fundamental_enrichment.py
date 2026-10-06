from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import settings
from core.application_factory import ApplicationFactory
from core.database import initialize_database
from database.database import Database
from database.migrations import fundamentals as fundamentals_migration
from database.repositories.fundamentals_repository import FundamentalsRepository
from engines.fundamental_contract import FundamentalInputContract
from providers.sqlite_fundamental_provider import SQLiteFundamentalProvider
from reconstruction.enrichment import StockEnricher
from services.fundamental_import_service import FundamentalFileImportService


COMPLETE_ROW = {
    "NSE Code": "RELIANCE",
    "ROCE": 16.0,
    "ROE": 18.0,
    "Sales growth": 12.0,
    "Profit growth": 15.0,
    "EPS growth": 11.0,
    "Debt to equity": 0.45,
    "Promoter holding": 50.3,
    "Pledged": 0.0,
}


def test_fundamentals_migration_upgrades_legacy_table(tmp_path):
    db = Database(tmp_path / "legacy.db")
    try:
        db.execute(
            """
            CREATE TABLE fundamentals(
                symbol TEXT PRIMARY KEY,
                roe REAL,
                roce REAL,
                debt_to_equity REAL,
                sales_growth REAL,
                profit_growth REAL,
                promoter_holding REAL,
                updated_at TEXT
            )
            """
        )

        fundamentals_migration.migrate(db)

        columns = {
            row["name"]
            for row in db.fetchall("PRAGMA table_info(fundamentals)")
        }
        assert {
            "eps_growth",
            "pledged",
            "source",
            "source_file",
            "as_of",
            "imported_at",
        } <= columns
    finally:
        db.close()


def test_csv_import_persists_complete_fundamentals(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    export = tmp_path / "fundamentals.csv"
    pd.DataFrame([COMPLETE_ROW]).to_csv(export, index=False)

    repository = FundamentalsRepository(db_path=str(db_path))
    service = FundamentalFileImportService(repository)
    report = service.import_file(export, source="screener")

    assert report["status"] == "imported"
    assert report["rows_read"] == 1
    assert report["imported"] == 1
    assert report["incomplete"] == 0

    row = repository.by_symbol("NSE:RELIANCE")
    assert row["symbol"] == "RELIANCE"
    assert row["roce"] == 16.0
    assert row["debt_to_equity"] == 0.45
    assert row["eps_growth"] == 11.0
    assert row["promoter_holding"] == 50.3
    assert row["pledged"] == 0.0
    assert row["source"] == "screener"
    assert row["source_file"] == "fundamentals.csv"
    repository.close()


def test_excel_import_supports_custom_column_mapping(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    export = tmp_path / "tijori.xlsx"
    pd.DataFrame(
        [{
            "Ticker": "INFY",
            "Capital Return": 31.0,
            "Equity Return": 28.0,
            "Revenue CAGR": 10.5,
            "Profit CAGR": 12.5,
            "EPS CAGR": 12.0,
            "D/E": 0.08,
            "Promoters": 14.6,
            "Pledge %": 0.0,
        }]
    ).to_excel(export, index=False)

    field_map = {
        "roce": "Capital Return",
        "roe": "Equity Return",
        "sales_growth": "Revenue CAGR",
        "profit_growth": "Profit CAGR",
        "eps_growth": "EPS CAGR",
        "debt_equity": "D/E",
        "promoter_holding": "Promoters",
        "pledged": "Pledge %",
    }
    repository = FundamentalsRepository(db_path=str(db_path))
    report = FundamentalFileImportService(repository).import_file(
        export,
        source="tijori",
        symbol_column="Ticker",
        field_map=field_map,
    )

    assert report["imported"] == 1
    row = repository.by_symbol("INFY")
    assert row["roce"] == 31.0
    assert row["roe"] == 28.0
    assert row["source"] == "tijori"
    repository.close()


def test_partial_import_is_persisted_but_fundamental_engine_contract_stays_fail_closed(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    export = tmp_path / "partial.csv"
    pd.DataFrame(
        [{"Symbol": "ABC", "ROCE": 20.0, "ROE": 18.0}]
    ).to_csv(export, index=False)

    repository = FundamentalsRepository(db_path=str(db_path))
    report = FundamentalFileImportService(repository).import_file(export)

    assert report["imported"] == 1
    assert report["incomplete"] == 1

    provider = SQLiteFundamentalProvider(
        repository=repository,
        max_age_days=365,
    )
    enricher = StockEnricher(providers={"fundamentals": provider})
    base = {"symbol": "ABC"}
    merged = enricher.merge(base, enricher.enrich(base))
    contract = FundamentalInputContract().validate(merged)

    assert contract.ready is False
    assert "sales_growth" in contract.missing
    assert "pledged" in contract.missing
    repository.close()


def test_sqlite_provider_returns_complete_fresh_snapshot_for_engine_contract(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    repository.save(
        {
            "symbol": "RELIANCE",
            "roce": 16.0,
            "roe": 18.0,
            "sales_growth": 12.0,
            "profit_growth": 15.0,
            "eps_growth": 11.0,
            "debt_to_equity": 0.45,
            "promoter_holding": 50.3,
            "pledged": 0.0,
            "source": "screener",
            "as_of": datetime.now(timezone.utc).isoformat(),
        }
    )

    provider = SQLiteFundamentalProvider(
        repository=repository,
        max_age_days=365,
    )
    snapshot = provider.get("RELIANCE")

    assert snapshot["_meta"]["stale"] is False
    assert snapshot["_meta"]["record_source"] == "screener"
    assert snapshot["_meta"]["missing"] == []
    assert snapshot["debt_equity"] == 0.45

    enricher = StockEnricher(providers={"fundamentals": provider})
    base = {"symbol": "RELIANCE"}
    merged = enricher.merge(base, enricher.enrich(base))
    assert FundamentalInputContract().validate(merged).ready is True
    repository.close()


def test_stale_database_snapshot_is_not_flattened_into_engine_contract(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    old = datetime.now(timezone.utc) - timedelta(days=400)
    repository.save(
        {
            "symbol": "STALE",
            "roce": 99.0,
            "roe": 99.0,
            "sales_growth": 99.0,
            "profit_growth": 99.0,
            "eps_growth": 99.0,
            "debt_to_equity": 0.0,
            "promoter_holding": 99.0,
            "pledged": 0.0,
            "source": "test",
            "as_of": old.isoformat(),
        }
    )

    provider = SQLiteFundamentalProvider(
        repository=repository,
        max_age_days=200,
    )
    enricher = StockEnricher(providers={"fundamentals": provider})
    base = {"symbol": "STALE"}
    merged = enricher.merge(base, enricher.enrich(base))

    assert merged["fundamental_data_quality"]["stale"] is True
    assert "roce" not in merged
    assert FundamentalInputContract().validate(merged).ready is False
    repository.close()


def test_application_factory_uses_only_sqlite_for_runtime_fundamentals():
    factory = ApplicationFactory()
    specs = factory.enricher.registry.providers("fundamentals")

    assert len(specs) == 1
    assert isinstance(specs[0].provider, SQLiteFundamentalProvider)
    assert "Tijori" not in repr(specs[0].provider.health())
    assert "Screener" not in repr(specs[0].provider.health())
    assert "Yahoo" not in repr(specs[0].provider.health())


def test_configured_startup_import_populates_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "trendforge.db"
    export = tmp_path / "fundamentals.csv"
    pd.DataFrame([COMPLETE_ROW]).to_csv(export, index=False)
    initialize_database(str(db_path))

    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    monkeypatch.setattr(settings, "FUNDAMENTALS_IMPORT_PATH", str(export))
    monkeypatch.setattr(settings, "FUNDAMENTALS_IMPORT_SOURCE", "screener")
    monkeypatch.setattr(settings, "FUNDAMENTALS_SYMBOL_COLUMN", None)
    monkeypatch.setattr(settings, "FUNDAMENTALS_FIELD_MAP_JSON", None)
    monkeypatch.setattr(settings, "FUNDAMENTALS_SHEET_NAME", "0")
    monkeypatch.setattr(settings, "FUNDAMENTALS_AS_OF", None)

    factory = ApplicationFactory()
    report = factory.import_fundamentals_if_configured()

    assert report["status"] == "imported"
    assert report["imported"] == 1

    provider = factory.enricher.registry.providers("fundamentals")[0].provider
    snapshot = provider.get("RELIANCE")
    assert snapshot["roce"] == 16.0
    assert snapshot["pledged"] == 0.0
