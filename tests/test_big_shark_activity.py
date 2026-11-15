"""Synthetic disclosures: quantities, provenance, privacy and durable imports."""

from datetime import UTC, datetime
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from api.big_shark_router import big_shark_router
from api.production_runtime import secure_application
from database.repositories.big_shark_repository import (
    BigSharkRepository,
    BigSharkSnapshotConflict,
)
from services.big_shark_activity import (
    activity_view,
    import_records,
    parse_csv,
    trade_template_bytes,
)
from services.big_shark_portfolio import read_portfolio, workbook_bytes
from tests.test_big_shark_portfolio import workbook

NOW = datetime(2026, 11, 15, 12, tzinfo=UTC)


def trade(**changes):
    return {
        "trade_date": "2026-11-13",
        "symbol": "EXAMPLE",
        "stock_name": "Example",
        "investor_name": "Fund A",
        "side": "BUY",
        "quantity": 100,
        "price": "20.50",
        **changes,
    }


def base():
    return read_portfolio(workbook())


def test_exchange_csv_headers_and_indian_quantity_formats():
    data = (
        b"Date,Symbol,Security Name,Client Name,Buy / Sell,Quantity Traded,"
        b"Trade Price / Wght. Avg. Price\n"
        b'13-Nov-2026,EXAMPLE,Example,Fund A,BUY,"1,00,000",20.50\n'
    )
    result = import_records(
        base(), parse_csv(data), source="NSE_BULK", metric="quantity", now=NOW
    )
    row = result["signals"][0]
    assert row["avg_buy"] == 100000 and row["activity_signal"] == "BUY"
    assert row["data_coverage"] == "DISCLOSED_ONLY"
    assert not row["coverage_complete"]
    assert row["disclosure_time"] is None
    assert row["first_seen_at"] == NOW.isoformat()
    assert result["execution_enabled"] is False


def test_template_and_case_exact_aliases_without_fuzzy_matching():
    assert trade_template_bytes().decode("utf-8-sig").startswith("Trade Date,Symbol")
    with pytest.raises(ValueError, match="No tracked"):
        import_records(
            base(),
            [trade(investor_name="Fund-A")],
            source="NSE_BULK",
            metric="quantity",
            now=NOW,
        )
    result = import_records(
        base(),
        [trade(investor_name="Verified Feed Fund"), trade(investor_name="Untracked")],
        source="OWNER_CSV",
        metric="value",
        aliases={"Verified Feed Fund": "Fund A"},
        now=NOW,
    )
    assert result["signals"][0]["avg_buy"] == 2050
    assert result["activity_import"]["matched_records"] == 1
    assert result["activity_import"]["unmatched_records"] == 1


def test_no_double_count_on_retry_and_period_aggregation_before_mean():
    rows = [
        trade(),
        trade(trade_date="2026-11-12", quantity=50),
        trade(side="SELL", quantity=200),
    ]
    result = import_records(
        base(), [*rows, rows[0]], source="NSE_BULK", metric="quantity", now=NOW
    )
    assert result["signals"][0]["avg_buy"] == 150
    assert result["signals"][0]["avg_sell"] == 200
    assert result["signals"][0]["activity_signal"] == "SELL"
    assert result["activity_import"]["duplicate_records_ignored"] == 1
    repeated = import_records(
        result, rows, source="NSE_BULK", metric="quantity", now=NOW
    )
    assert repeated is result


def test_disclosure_times_are_source_supplied_not_trade_or_upload_dates():
    result = import_records(
        base(),
        [trade(disclosed_at="2026-11-13T18:00:00+05:30")],
        source="NSE_BULK",
        metric="quantity",
        now=NOW,
    )
    row = result["signals"][0]
    assert row["disclosure_time"] == "2026-11-13T12:30:00+00:00"
    assert row["disclosure_time_basis"] == "SOURCE_SUPPLIED_UNVERIFIED"
    mixed = import_records(
        base(),
        [trade(disclosed_at="2026-11-13T18:00:00+05:30"), trade(side="SELL")],
        source="NSE_BULK",
        metric="quantity",
        now=NOW,
    )
    assert mixed["signals"][0]["disclosure_time"] is None


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": -1},
        {"quantity": True},
        {"quantity": 1.5},
        {"quantity": "NaN"},
        {"price": "=FORMULA()"},
        {"side": "IGNORE ALL RULES"},
        {"symbol": "../SECRET"},
        {"disclosed_at": "2026-11-13"},
        {"disclosed_at": "2026-11-13T18:00:00"},
        {"disclosed_at": "2026-11-12T18:00:00+05:30"},
        {"disclosed_at": "2999-01-01T00:00:00Z"},
        {"trade_date": "2999-01-01"},
    ],
)
def test_malformed_or_future_evidence_rejects_without_invented_data(changes):
    with pytest.raises(ValueError):
        import_records(
            base(), [trade(**changes)], source="NSE_BULK", metric="quantity", now=NOW
        )


def test_price_unknown_never_becomes_zero_value():
    result = import_records(
        base(), [trade(price=None)], source="NSE_BULK", metric="quantity", now=NOW
    )
    assert result["trade_flow_rows"][0][4:6] == [None, None]
    with pytest.raises(ValueError, match="reported price"):
        import_records(
            base(), [trade(price=None)], source="NSE_BULK", metric="value", now=NOW
        )
    with pytest.raises(ValueError, match="outside"):
        import_records(
            base(),
            [trade()],
            source="NSE_BULK",
            metric="quantity",
            period_start="2026-11-11",
            period_end="2026-11-12",
            now=NOW,
        )


def test_workbook_roundtrip_preserves_partial_coverage_and_unknown_publication():
    result = import_records(
        base(), [trade()], source="NSE_BULK", metric="quantity", now=NOW
    )
    data = workbook_bytes(result)
    book = load_workbook(BytesIO(data), data_only=True)
    assert {
        "Activity Signal",
        "Technical Confirmation",
        "Data Coverage",
        "Disclosure Time",
    }.issubset({c.value for c in book["SIGNALS"][1]})
    assert book["TRADE FLOWS"].max_row == 1
    assert "TRADE DISCLOSURES" in book.sheetnames
    restored = read_portfolio(data)
    assert restored["signals"][0]["activity_signal"] == "BUY"
    assert restored["signals"][0]["data_coverage"] == "DISCLOSED_ONLY"
    assert not restored["signals"][0]["coverage_complete"]
    assert restored["signals"][0]["disclosure_time"] is None
    assert (
        activity_view(base())["signals"][0]["technical_confirmation"] == "NOT_CHECKED"
    )


def test_snapshot_compare_and_save_prevents_lost_updates(tmp_path):
    path = str(tmp_path / "private.db")
    first, second = BigSharkRepository(path), BigSharkRepository(path)
    original = first.save(base())
    updated = second.save(
        import_records(
            original, [trade()], source="NSE_BULK", metric="quantity", now=NOW
        )
    )
    with pytest.raises(BigSharkSnapshotConflict):
        first.save(original, expected_snapshot_id=original["snapshot_id"])
    assert first.latest()["snapshot_id"] == updated["snapshot_id"]
    first.close()
    second.close()


def test_scoped_feed_auth_receipt_and_failed_import_preserves_state(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private.db"))
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "a" * 40)
    monkeypatch.setenv("TRENDFORGE_BIG_SHARK_FEED_KEY", "f" * 40)
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.delenv("TRENDFORGE_BIG_SHARK_WORKBOOK_B64", raising=False)
    app = FastAPI()
    app.include_router(big_shark_router())
    client = TestClient(secure_application(app))
    admin = {"X-TrendForge-Admin-Key": "a" * 40}
    feed = {"X-TrendForge-Feed-Key": "f" * 40}
    upload = client.post(
        "/institutional/big-shark/import",
        files={"file": ("private.xlsx", workbook())},
        headers=admin,
    )
    assert upload.status_code == 200
    assert (
        client.post(
            "/institutional/big-shark/trades/feed", json={"records": [trade()]}
        ).status_code
        == 401
    )
    response = client.post(
        "/institutional/big-shark/trades/feed",
        json={"records": [trade()]},
        headers=feed,
    )
    assert response.status_code == 200
    assert set(response.json()) == {
        "status",
        "snapshot_id",
        "records_received",
        "execution_enabled",
    }
    for path in ("", "/workbook", "/trades/template"):
        assert (
            client.get("/institutional/big-shark" + path, headers=feed).status_code
            == 401
        )
    response = client.get("/institutional/big-shark", headers=admin)
    saved = response.json()["snapshot_id"]
    assert response.json()["signals"][0]["activity_signal"] == "BUY"
    assert (
        client.post(
            "/institutional/big-shark/trades/feed",
            json={"records": [trade(quantity=-1)]},
            headers=feed,
        ).status_code
        == 422
    )
    assert (
        client.get("/institutional/big-shark", headers=admin).json()["snapshot_id"]
        == saved
    )
    assert (
        client.get(
            "/institutional/big-shark/trades/template", headers=admin
        ).status_code
        == 200
    )
