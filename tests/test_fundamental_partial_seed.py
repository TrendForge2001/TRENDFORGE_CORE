from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.database import initialize_database
from database.repositories.fundamentals_repository import FundamentalsRepository
from database.repositories.instrument_repository import InstrumentRepository
from services.fundamental_data_manager import FundamentalDataManager
from services.fundamental_partial_seed_service import FundamentalPartialSeedService
from services.fundamental_symbol_resolver import FundamentalSymbolResolver


def step1_row(name: str, *, roce=30.0, sales=20.0, profit=40.0, de=0.2):
    return {
        "Name": name,
        "ROCE": roce,
        "SalesCAGR": sales,
        "ProfitCAGR": profit,
        "DE": de,
    }


def instrument(token: int, symbol: str, name: str):
    return {
        "instrument_token": token,
        "exchange_token": token + 1000,
        "tradingsymbol": symbol,
        "name": name,
        "last_price": 0.0,
        "expiry": "",
        "strike": 0.0,
        "tick_size": 0.05,
        "lot_size": 1,
        "instrument_type": "EQ",
        "segment": "NSE",
        "exchange": "NSE",
    }


def test_step1_preview_uses_explicit_map_and_never_writes(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    source = tmp_path / "Step1_Filtered_Stocks.xlsx"
    pd.DataFrame(
        [
            step1_row("Lupin"),
            step1_row("Unknown Company"),
        ]
    ).to_excel(source, index=False)

    service = FundamentalPartialSeedService(db_path=str(db_path))
    report = service.process_file(
        source,
        symbol_map={"Lupin": "LUPIN"},
    )

    assert report["status"] == "preview"
    assert report["mode"] == "preview"
    assert report["rows_read"] == 2
    assert report["resolved"] == 1
    assert report["unresolved"] == 1
    assert report["invalid"] == 0
    assert report["applied"] == 0
    assert report["database_records"] == 0

    row = report["resolved_rows"][0]
    assert row["symbol"] == "LUPIN"
    assert row["resolution_method"] == "explicit_map"
    assert set(row["available_fields"]) == {
        "roce",
        "sales_growth",
        "profit_growth",
        "debt_equity",
    }
    assert row["after_completeness_pct"] == 50.0

    unresolved = report["unresolved_rows"][0]
    assert unresolved["identifier"] == "Unknown Company"
    assert unresolved["status"] == "unresolved"


def test_step1_apply_merges_partial_fields_without_erasing_existing_values(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    repository = FundamentalsRepository(db_path=str(db_path))
    manager = FundamentalDataManager(repository=repository, max_age_days=365)

    manager.upsert(
        "LUPIN",
        {
            "roe": 18.0,
            "eps_growth": 15.0,
            "promoter_holding": 47.0,
            "pledged": 0.0,
        },
        source="manual_verified",
        as_of=datetime.now(timezone.utc).isoformat(),
    )

    source = tmp_path / "Step1_Filtered_Stocks.xlsx"
    pd.DataFrame([step1_row("Lupin")]).to_excel(source, index=False)

    service = FundamentalPartialSeedService(manager=manager)
    report = service.process_file(
        source,
        apply=True,
        symbol_map={"Lupin": "LUPIN"},
        source="step1_seed",
    )

    assert report["status"] == "applied"
    assert report["applied"] == 1

    result = manager.inspect("LUPIN")
    assert result is not None
    values = result["fundamentals"]
    assert values["roce"] == 30.0
    assert values["sales_growth"] == 20.0
    assert values["profit_growth"] == 40.0
    assert values["debt_equity"] == 0.2
    assert values["roe"] == 18.0
    assert values["eps_growth"] == 15.0
    assert values["promoter_holding"] == 47.0
    assert values["pledged"] == 0.0
    assert result["quality"]["completeness_pct"] == 100.0
    assert result["quality"]["ready"] is True
    repository.close()


def test_resolver_uses_exact_instrument_symbol_or_name_only(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))
    instruments = InstrumentRepository(db_path=str(db_path))
    instruments.save_all(
        [
            instrument(1, "LUPIN", "Lupin"),
            instrument(2, "FORCEMOT", "Force Motors"),
        ]
    )

    resolver = FundamentalSymbolResolver(
        instrument_repository=instruments,
    )

    direct = resolver.resolve("Lupin")
    assert direct.symbol == "LUPIN"
    assert direct.method == "instrument_symbol_exact"

    by_name = resolver.resolve("Force Motors")
    assert by_name.symbol == "FORCEMOT"
    assert by_name.method == "instrument_name_exact"

    unresolved = resolver.resolve("Force Motor")
    assert unresolved.symbol is None
    assert unresolved.status == "unresolved"

    instruments.close()


def test_explicit_symbol_column_is_authoritative_without_instrument_data(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    source = tmp_path / "partial.csv"
    pd.DataFrame(
        [
            {
                "Symbol": "NSE:ABC",
                "ROCE": 25.0,
                "SalesCAGR": 12.0,
                "ProfitCAGR": 15.0,
                "DE": 0.3,
            }
        ]
    ).to_csv(source, index=False)

    service = FundamentalPartialSeedService(db_path=str(db_path))
    report = service.process_file(source)

    assert report["resolved"] == 1
    assert report["unresolved"] == 0
    assert report["resolved_rows"][0]["symbol"] == "ABC"
    assert (
        report["resolved_rows"][0]["resolution_method"]
        == "explicit_symbol_column"
    )


def test_invalid_legacy_values_are_reported_and_not_applied(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    source = tmp_path / "invalid.xlsx"
    pd.DataFrame(
        [
            {
                "Symbol": "ABC",
                "ROCE": 1500.0,
                "SalesCAGR": 10.0,
                "ProfitCAGR": 10.0,
                "DE": 0.2,
            }
        ]
    ).to_excel(source, index=False)

    service = FundamentalPartialSeedService(db_path=str(db_path))
    report = service.process_file(source, apply=True)

    assert report["resolved"] == 0
    assert report["invalid"] == 1
    assert report["applied"] == 0
    assert report["database_records"] == 0
    assert report["invalid_rows"][0]["invalid"] == ["roce"]


def test_symbol_map_can_be_loaded_from_csv(tmp_path):
    db_path = tmp_path / "trendforge.db"
    initialize_database(str(db_path))

    mapping = tmp_path / "symbol_map.csv"
    pd.DataFrame(
        [
            {"Name": "Lupin", "Symbol": "LUPIN"},
            {"Name": "Force Motors", "Symbol": "FORCEMOT"},
        ]
    ).to_csv(mapping, index=False)

    source = tmp_path / "legacy.xlsx"
    pd.DataFrame(
        [
            step1_row("Lupin"),
            step1_row("Force Motors"),
        ]
    ).to_excel(source, index=False)

    service = FundamentalPartialSeedService(db_path=str(db_path))
    report = service.process_file(source, symbol_map=mapping)

    assert report["resolved"] == 2
    assert {
        item["symbol"] for item in report["resolved_rows"]
    } == {"LUPIN", "FORCEMOT"}


def test_unresolved_mapping_frame_is_fillable_template():
    report = {
        "unresolved_rows": [
            {
                "identifier": "GE Vernova T&D",
                "status": "unresolved",
                "candidates": [],
            },
            {
                "identifier": "Example Co",
                "status": "ambiguous",
                "candidates": ["AAA", "BBB"],
            },
        ]
    }

    frame = FundamentalPartialSeedService.unresolved_mapping_frame(report)

    assert list(frame.columns) == ["Name", "Symbol", "Status", "Candidates"]
    assert frame.iloc[0]["Name"] == "GE Vernova T&D"
    assert frame.iloc[0]["Symbol"] == ""
    assert frame.iloc[1]["Candidates"] == "AAA,BBB"
