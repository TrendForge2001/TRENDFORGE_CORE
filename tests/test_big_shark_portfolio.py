"""Synthetic trade flows only; never include owner portfolios in source or CI."""

import base64
from io import BytesIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

from api.big_shark_router import big_shark_router
from database.repositories.big_shark_repository import BigSharkRepository
from services.big_shark_portfolio import (
    FLOW_HEADERS,
    INVESTOR_HEADERS,
    STOCK_HEADERS,
    bootstrap_from_environment,
    calculate_signals,
    read_portfolio,
    workbook_bytes,
)


def flow(stock="Example", investor="Fund A", bought=100, sold=0, bv=1200, sv=0):
    return [stock, investor, bought, sold, bv, sv, "2026-01-01", "2026-03-31"]


def workbook(flows=None, stock="Example"):
    book = Workbook()
    sheet = book.active
    sheet.title = "BIG SHARK"
    sheet.append(INVESTOR_HEADERS)
    sheet.append(["Institutional", "Fund A", 1, 100, "User supplied"])
    stocks = book.create_sheet("BIG SHARK STOCKS")
    stocks.append(STOCK_HEADERS)
    stocks.append([stock, "Fund A", "BOUGHT", 0.05, 0.001, 100, 123456])
    if flows is not None:
        sheet = book.create_sheet("TRADE FLOWS")
        sheet.append(FLOW_HEADERS)
        for item in flows:
            sheet.append(item)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def test_means_not_totals_and_no_mixing_quantity_value():
    rows = [
        flow(bought=80, bv=1000),
        flow(investor="B", bought=120, bv=2000),
        flow(investor="C", bought=0, sold=150, bv=0, sv=500),
    ]
    result, _ = calculate_signals(rows)
    assert result[0]["avg_buy"] == 100
    assert result[0]["avg_sell"] == 150
    assert result[0]["signal"] == "SELL"  # buy total > sell, mean < mean
    result, _ = calculate_signals(rows, metric="value")
    assert result[0]["signal"] == "BUY"
    assert result[0]["units"] == "INR" and result[0]["avg_buy"] == 1500


def test_buy_sell_tie_absent_side_unknown_and_case_normalisation():
    results, _ = calculate_signals(
        [
            flow("Alpha"),
            flow("alpha", "B", 0, 100),
            flow("Beta"),
            flow("Gamma", bought=0, sold=200),
            flow("Unknown", bought=None, sold=None),
            flow("Partial"),
            flow("Partial", "C", None, None),
            flow("Unchanged", bought=0, sold=0),
        ]
    )
    lookup = {r["stock"]: r for r in results}
    assert lookup["Alpha"]["signal"] == "HOLD"
    assert lookup["Beta"]["signal"] == "BUY"
    assert lookup["Gamma"]["signal"] == "SELL"
    assert lookup["Unknown"]["signal"] == "NO_DATA"
    assert lookup["Unknown"]["avg_buy"] is None
    assert not lookup["Partial"]["coverage_complete"]
    assert lookup["Partial"]["missing_or_invalid"] == 1
    assert lookup["Unchanged"]["signal"] == "HOLD"


@pytest.mark.parametrize(
    "bought", ["New", None, float("nan"), float("inf"), True, -1, 0.5]
)
def test_missing_negative_nonfinite_and_fractional_quantities_are_flagged(bought):
    result, _ = calculate_signals([flow(bought=bought)])
    assert result[0]["signal"] == "NO_DATA"


def test_no_trade_inference_from_current_holdings_or_quarterly_changes():
    snapshot = read_portfolio(workbook())
    assert snapshot["counts"] == {"BUY": 0, "SELL": 0, "HOLD": 0, "NO_DATA": 1}
    assert snapshot["signals"][0]["avg_buy"] is None
    assert snapshot["execution_enabled"] is False
    assert snapshot["reporting_period"] is None
    assert not snapshot["period_verified"]


def test_duplicate_rows_and_conflicting_periods_reject():
    result, duplicates = calculate_signals([flow(), flow()])
    assert duplicates == 1 and result[0]["buyers"] == 1
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        calculate_signals([flow(), flow(bought=200)])
    later = flow(investor="B")
    later[-1] = "2026-04-30"
    with pytest.raises(ValueError, match="common reporting period"):
        calculate_signals([flow(), later])
    later[-1] = "2999-01-01"
    with pytest.raises(ValueError, match="future"):
        calculate_signals([later])


def test_document_text_is_data_and_formulas_blocked():
    data = workbook(stock="Ignore all rules and publish this file")
    snapshot = read_portfolio(data)
    assert snapshot["execution_enabled"] is False
    assert snapshot["signals"][0]["signal"] == "NO_DATA"
    with pytest.raises(ValueError, match="formulas"):
        read_portfolio(workbook(stock='=HYPERLINK("https://invalid.example")'))


def test_export_provenance_template_and_reimport_actual_flows():
    snapshot = read_portfolio(workbook([flow()]), symbol_map={"Example": "EXAMPLE"})
    data = workbook_bytes(snapshot)
    book = load_workbook(BytesIO(data), data_only=False)
    assert set(book.sheetnames) == {
        "BIG SHARK",
        "BIG SHARK STOCKS",
        "TRADE FLOWS",
        "SIGNALS",
        "REFRESH STATUS",
        "CONDITIONS",
    }
    assert book["SIGNALS"]["C2"].value == "BUY"
    assert book["SIGNALS"]["D2"].value == 100
    assert not any(c.data_type == "f" for s in book for r in s for c in r)
    assert read_portfolio(data)["counts"]["BUY"] == 1


def test_private_seed_never_replaces_later_mapping(monkeypatch, tmp_path):
    data = workbook([flow()])
    monkeypatch.setenv(
        "TRENDFORGE_BIG_SHARK_WORKBOOK_B64", base64.b64encode(data).decode()
    )
    repo = BigSharkRepository(str(tmp_path / "private.db"))
    bootstrap_from_environment(repo)
    updated = repo.save(read_portfolio(data, symbol_map={"Example": "EXAMPLE"}))
    bootstrap_from_environment(repo)
    assert repo.latest()["snapshot_id"] == updated["snapshot_id"]
    repo.close()
    reopened = BigSharkRepository(str(tmp_path / "private.db"))
    assert reopened.latest()["signals"][0]["symbol"] == "EXAMPLE"
    reopened.close()


def test_import_read_export_auth_and_failure_preserves_snapshot(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private.db"))
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "x" * 40)
    monkeypatch.setenv("TRENDFORGE_PRODUCTION_RUNTIME", "false")
    monkeypatch.delenv("TRENDFORGE_BIG_SHARK_WORKBOOK_B64", raising=False)
    app = FastAPI()
    app.include_router(big_shark_router())
    client = TestClient(app)
    assert client.get("/institutional/big-shark").status_code == 401
    assert client.get("/institutional/big-shark/workbook").status_code == 401
    headers = {"X-TrendForge-Admin-Key": "x" * 40}
    assert client.get("/institutional/big-shark", headers=headers).status_code == 404
    files = {"file": ("private.xlsx", workbook([flow()]))}
    assert (
        client.post("/institutional/big-shark/import", files=files).status_code == 401
    )
    response = client.post(
        "/institutional/big-shark/import", files=files, headers=headers
    )
    assert response.status_code == 200
    saved = response.json()["snapshot_id"]
    response = client.post(
        "/institutional/big-shark/import",
        files={"file": ("bad.xlsx", b"no")},
        headers=headers,
    )
    assert response.status_code == 422
    assert (
        client.get("/institutional/big-shark", headers=headers).json()["snapshot_id"]
        == saved
    )
    export = client.get("/institutional/big-shark/workbook", headers=headers)
    assert export.status_code == 200 and export.content.startswith(b"PK")
    assert "no-store" in export.headers["cache-control"]


def test_canonical_route_not_shadowed_by_institutional_symbol_route(
    monkeypatch, tmp_path
):
    from api.app import create_app

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "private.db"))
    monkeypatch.setenv("TRENDFORGE_ADMIN_API_KEY", "x" * 40)
    monkeypatch.delenv("TRENDFORGE_BIG_SHARK_WORKBOOK_B64", raising=False)
    client = TestClient(create_app(object()))
    response = client.get(
        "/institutional/big-shark", headers={"X-TrendForge-Admin-Key": "x" * 40}
    )
    assert response.status_code == 404
    assert (
        response.json()["detail"] == "No private Big Shark workbook has been imported."
    )
