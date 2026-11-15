"""Private workbook ingestion and the owner's explicit actual-trade rule.

Workbook text is data, never executable instructions. Holdings are not trades.
No provider refresh, broker order, or fuzzy symbol match occurs on import.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill

MAX_WORKBOOK_BYTES = 2 * 1024 * 1024
_BOOTSTRAP_LOCK = threading.RLock()
STOCK_HEADERS = (
    "Stock Name",
    "Investor Name",
    "Action",
    "Holding %",
    "Change From Prev. Qtr.",
    "Holding Value (₹ Cr)",
    "Quantity Held",
)
INVESTOR_HEADERS = (
    "Category",
    "Investor / Portfolio",
    "Company Holdings",
    "Networth (₹ Cr)",
    "Source",
)
FLOW_HEADERS = (
    "Stock Name",
    "Investor Name",
    "Bought Quantity",
    "Sold Quantity",
    "Bought Value (₹)",
    "Sold Value (₹)",
    "Period Start",
    "Period End",
)
RULE = "mean_actual_bought_vs_mean_actual_sold_per_active_investor_v1"
SOURCE_URLS = (
    "https://www.moneycontrol.com/india-investors-portfolio/",
    "https://www.moneycontrol.com/india-investors-portfolio/top-stocks-bought-sold",
)


def _text(value):
    return " ".join(str(value or "").strip().split())[:300]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _sheet_rows(sheet, headers):
    if sheet.max_row > 10002 or sheet.max_column > 30:
        raise ValueError("Workbook exceeds the supported row or column limit.")
    values = list(sheet.iter_rows(values_only=True))
    start = next(
        (
            i
            for i, row in enumerate(values[:10])
            if tuple(row[: len(headers)]) == headers
        ),
        None,
    )
    if start is None:
        raise ValueError(f"Required column headers are missing in {sheet.title}.")
    return [
        list(row[: len(headers)])
        for row in values[start + 1 :]
        if any(v is not None for v in row[: len(headers)])
    ]


def calculate_signals(rows, symbol_map=None, *, metric="quantity", stock_names=()):
    """One period, side means of actual flows; never derive trades from holdings."""
    if metric not in {"quantity", "value"}:
        raise ValueError("Choose actual quantity or actual INR value.")
    grouped = defaultdict(list)
    names = {}
    for name in stock_names:
        canonical = names.setdefault(_text(name).casefold(), _text(name))
        grouped[canonical]  # Include stocks awaiting actual trade data.
    mapping = {
        str(k).strip().casefold(): str(v).strip().upper()
        for k, v in (symbol_map or {}).items()
    }
    seen, periods = {}, set()
    duplicates = 0
    for row in rows:
        stock, investor, bq, sq, bv, sv, start, end = row
        stock, investor = _text(stock), _text(investor)
        if not stock or not investor:
            raise ValueError("Each trade-flow row needs a stock and investor name.")
        try:
            first, last = (
                date.fromisoformat(_text(start)),
                date.fromisoformat(_text(end)),
            )
        except ValueError:
            raise ValueError(
                "Trade periods require YYYY-MM-DD start and end dates."
            ) from None
        if first > last or last > date.today():
            raise ValueError(
                "Trade periods must be ordered and cannot end in the future."
            )
        periods.add((first, last))
        if len(periods) > 1:
            raise ValueError("Use one common reporting period per imported snapshot.")
        key = (stock.casefold(), investor.casefold())
        if key in seen:
            if seen[key] != row:
                raise ValueError("Conflicting duplicate stock/investor trade rows.")
            duplicates += 1
            continue
        seen[key] = row
        bought, sold = (
            (_number(bq), _number(sq))
            if metric == "quantity"
            else (_number(bv), _number(sv))
        )
        valid = (
            bought is not None
            and sold is not None
            and 0 <= bought <= 1e15
            and 0 <= sold <= 1e15
        )
        if valid and metric == "quantity":
            valid = bought.is_integer() and sold.is_integer()
        stock = names.setdefault(stock.casefold(), stock)
        grouped[stock].append(
            (
                Decimal(str(bought)) if valid else None,
                Decimal(str(sold)) if valid else None,
            )
        )
    signals = []
    for stock, observations in sorted(
        grouped.items(), key=lambda item: item[0].casefold()
    ):
        known = [(b, s) for b, s in observations if b is not None and s is not None]
        buys = [b for b, _ in known if b > 0]
        sells = [s for _, s in known if s > 0]
        avg_buy = sum(buys) / len(buys) if buys else Decimal(0)
        avg_sell = sum(sells) / len(sells) if sells else Decimal(0)
        signal = (
            "NO_DATA"
            if not known
            else "BUY"
            if avg_buy > avg_sell
            else "SELL"
            if avg_sell > avg_buy
            else "HOLD"
        )
        signals.append(
            {
                "stock": stock,
                "symbol": mapping.get(stock.casefold()),
                "signal": signal,
                "avg_buy": float(avg_buy) if known else None,
                "avg_sell": float(avg_sell) if known else None,
                "metric": metric,
                "units": "shares" if metric == "quantity" else "INR",
                "period_start": str(min(periods)[0]) if periods else None,
                "period_end": str(min(periods)[1]) if periods else None,
                "buyers": len(buys),
                "sellers": len(sells),
                "observations": len(observations),
                "missing_or_invalid": len(observations) - len(known),
                "coverage_complete": bool(known) and len(known) == len(observations),
                "status": "Actual trade data supplied"
                if known
                else "Awaiting actual bought/sold quantities or values",
            }
        )
    return signals, duplicates


def read_portfolio(
    data: bytes, *, symbol_map=None, reporting_period=None, metric="quantity"
):
    if not data or len(data) > MAX_WORKBOOK_BYTES:
        raise ValueError("Upload an XLSX workbook of at most 2 MB.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 20 * 1024 * 1024:
                raise ValueError("Expanded workbook exceeds 20 MB.")
            if any("vbaproject" in name.lower() for name in archive.namelist()):
                raise ValueError("Macro-enabled workbooks are not accepted.")
            for name in archive.namelist():
                if name.lower().endswith((".xml", ".rels")):
                    xml = archive.read(name).replace(b"\x00", b"").upper()
                    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                        raise ValueError("Workbook XML declarations are not accepted.")
        book = load_workbook(BytesIO(data), data_only=False, keep_links=False)
    except (BadZipFile, KeyError, OSError) as exc:
        raise ValueError("Invalid XLSX workbook.") from exc
    try:
        for sheet in book:
            if sheet.max_row > 10002 or sheet.max_column > 30:
                raise ValueError("Workbook exceeds the row or column limit.")
            for row in sheet:
                if any(cell.data_type == "f" for cell in row):
                    raise ValueError(
                        "Upload values only; workbook formulas are not executed."
                    )
        if not {"BIG SHARK", "BIG SHARK STOCKS"}.issubset(book.sheetnames):
            raise ValueError("Expected BIG SHARK and BIG SHARK STOCKS sheets.")
        stocks = _sheet_rows(book["BIG SHARK STOCKS"], STOCK_HEADERS)
        investors = _sheet_rows(book["BIG SHARK"], INVESTOR_HEADERS)
        if not stocks:
            raise ValueError("The stock sheet contains no holding rows.")

        # Keep only bounded JSON scalar data. Cell content cannot change settings.
        def clean(rows):
            def cell_value(value):
                if isinstance(value, datetime):
                    return value.date().isoformat()
                if isinstance(value, date):
                    return value.isoformat()
                return (
                    _number(value) if isinstance(value, (int, float)) else _text(value)
                )

            return [[cell_value(v) for v in row] for row in rows]

        stocks, investors = clean(stocks), clean(investors)
        flows = (
            clean(_sheet_rows(book["TRADE FLOWS"], FLOW_HEADERS))
            if "TRADE FLOWS" in book.sheetnames
            else []
        )
        signals, duplicates = calculate_signals(
            flows, symbol_map, metric=metric, stock_names=[r[0] for r in stocks]
        )
        if reporting_period is not None:
            import re

            if not re.fullmatch(r"\d{4}-Q[1-4]", reporting_period):
                raise ValueError("Reporting period must use YYYY-Q1 through YYYY-Q4.")
            year, quarter = int(reporting_period[:4]), int(reporting_period[-1])
            if (year, quarter) > (date.today().year, (date.today().month - 1) // 3 + 1):
                raise ValueError("A future reporting quarter cannot be imported.")
        snapshot = {
            "rule": RULE,
            "metric": metric,
            "trade_flow_rows": flows,
            "imported_at": datetime.now(UTC).isoformat(),
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "original_workbook_sha256": hashlib.sha256(data).hexdigest(),
            "reporting_period": reporting_period,
            "period_verified": False,
            "refresh_status": "recalculated_uploaded_values_live_filings_not_verified",
            "source_urls": list(SOURCE_URLS),
            "stock_rows": stocks,
            "investor_rows": investors,
            "signals": signals,
            "duplicate_rows_ignored": duplicates,
            "counts": {
                s: sum(row["signal"] == s for row in signals)
                for s in ("BUY", "SELL", "HOLD", "NO_DATA")
            },
            "execution_enabled": False,
        }
        if "TRADE DISCLOSURES" in book.sheetnames:
            from services.big_shark_activity import TRADE_HEADERS, import_records

            entries = clean(
                _sheet_rows(
                    book["TRADE DISCLOSURES"], (*TRADE_HEADERS, "Portfolio Investor")
                )
            )
            if entries:
                fields = (
                    "trade_date",
                    "symbol",
                    "stock_name",
                    "investor_name",
                    "side",
                    "quantity",
                    "price",
                    "disclosed_at",
                    "trade_id",
                )
                records = [dict(zip(fields, r[:9], strict=True)) for r in entries]
                aliases = {r[3]: r[9] for r in entries if r[9]}
                metadata = (
                    dict(_sheet_rows(book["ACTIVITY METADATA"], ("Field", "Value")))
                    if "ACTIVITY METADATA" in book.sheetnames
                    else {}
                )
                snapshot = import_records(
                    snapshot,
                    records,
                    source=metadata.get("Source", "OWNER_CSV"),
                    metric=metric,
                    aliases=aliases,
                    period_start=metadata.get("Period Start"),
                    period_end=metadata.get("Period End"),
                )
        return snapshot
    finally:
        book.close()


def workbook_bytes(snapshot):
    """Export recalculated values with provenance; neutralize Excel formulas."""
    from openpyxl import Workbook

    from services.big_shark_activity import TRADE_HEADERS, activity_view

    snapshot = activity_view(snapshot)

    book = Workbook()
    book.remove(book.active)

    def write(name, rows):
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                65, max(16, max(len(str(c.value or "")) for c in column) + 2)
            )
        return sheet

    write("BIG SHARK", [INVESTOR_HEADERS, *snapshot["investor_rows"]])
    # Disclosure-only aggregates must not become an attested complete trade ledger
    # when this workbook is reimported. Keep the original individual records.
    flow_rows = (
        [] if snapshot.get("trade_records") else snapshot.get("trade_flow_rows", [])
    )
    flows = write("TRADE FLOWS", [FLOW_HEADERS, *flow_rows])
    if snapshot.get("trade_records"):
        keys = (
            "trade_date",
            "symbol",
            "stock_name",
            "investor_name",
            "side",
            "quantity",
            "price",
            "disclosed_at",
            "trade_id",
            "matched_investor",
        )
        write(
            "TRADE DISCLOSURES",
            [
                [*TRADE_HEADERS, "Portfolio Investor"],
                *[[r.get(k) for k in keys] for r in snapshot["trade_records"]],
            ],
        )
        write(
            "ACTIVITY METADATA",
            [
                ["Field", "Value"],
                ["Source", snapshot.get("activity_source")],
                ["Period Start", snapshot.get("activity_window", {}).get("start")],
                ["Period End", snapshot.get("activity_window", {}).get("end")],
                ["Coverage", "DISCLOSED_ONLY"],
            ],
        )
    from openpyxl.worksheet.datavalidation import DataValidation

    for kind, columns in (("whole", "C2:D10001"), ("decimal", "E2:F10001")):
        validation = DataValidation(
            type=kind, operator="greaterThanOrEqual", formula1=0
        )
        validation.allow_blank = True
        validation.showErrorMessage = True
        validation.errorTitle = "Actual trade amount required"
        validation.error = (
            "Use a non-negative number; enter zero for a known absent side."
        )
        flows.add_data_validation(validation)
        validation.add(columns)
    stocks = write("BIG SHARK STOCKS", [STOCK_HEADERS, *snapshot["stock_rows"]])
    for row in stocks.iter_rows(min_row=2):
        row[3].number_format = row[4].number_format = "0.00%"
    columns = (
        "stock",
        "symbol",
        "activity_signal",
        "avg_buy",
        "avg_sell",
        "buyers",
        "sellers",
        "observations",
        "missing_or_invalid",
        "coverage_complete",
        "units",
        "period_start",
        "period_end",
        "technical_confirmation",
        "data_coverage",
        "disclosure_time",
        "first_seen_at",
    )
    headings = {
        "activity_signal": "Activity Signal",
        "technical_confirmation": "Technical Confirmation",
        "data_coverage": "Data Coverage",
        "disclosure_time": "Disclosure Time",
    }
    signals = write(
        "SIGNALS",
        [
            [headings.get(k, k) for k in columns],
            *[[r.get(k) for k in columns] for r in snapshot["signals"]],
        ],
    )
    for row in signals.iter_rows(min_row=2):
        row[2].fill = PatternFill(
            "solid",
            fgColor={"BUY": "C6EFCE", "SELL": "FFC7CE", "HOLD": "FFEB9C"}.get(
                row[2].value, "DDDDDD"
            ),
        )
        row[3].number_format = row[4].number_format = "0.000000"
    write(
        "REFRESH STATUS",
        [
            ["Field", "Value"],
            ["Calculated at (UTC)", snapshot["imported_at"]],
            [
                "Source workbook SHA256",
                snapshot.get("original_workbook_sha256", snapshot["source_sha256"]),
            ],
            ["Activity source", snapshot.get("activity_source", "Uploaded workbook")],
            [
                "Disclosure time",
                "Unknown unless explicitly supplied; first seen is recorded separately",
            ],
            [
                "Holdings reporting quarter",
                snapshot.get("reporting_period")
                or "UNKNOWN — absent from uploaded workbook",
            ],
            ["Live refresh", snapshot["refresh_status"]],
            [
                "Signal input",
                "Actual " + snapshot["metric"] + " only; holdings are not trades",
            ],
            ["Investor source", SOURCE_URLS[0]],
            ["Stock source", SOURCE_URLS[1]],
            [
                "Orders",
                "Signal generation only; broker execution is disabled here",
            ],
        ],
    )
    write(
        "CONDITIONS",
        [
            ["Condition", "Definition"],
            [
                "BUY",
                "Average actual bought quantity/value > average actual sold "
                "quantity/value",
            ],
            [
                "SELL",
                "Average actual sold quantity/value > average actual bought "
                "quantity/value",
            ],
            [
                "HOLD",
                "Equal averages with at least one complete actual trade observation",
            ],
            [
                "NO_DATA",
                "Awaiting actual bought/sold quantities or values; no proxy signals",
            ],
            [
                "Averages",
                "Bought amount per buying investor; sold amount per selling investor",
            ],
            [
                "Metric",
                "Choose shares OR INR traded value for the whole snapshot; never "
                "mix units",
            ],
            [
                "Zero vs missing",
                "Enter an explicit zero for a known absent side; a blank is unknown",
            ],
            ["Duplicates", "One aggregate row per stock/investor and reporting period"],
            [
                "Period",
                "Use one common start/end date in YYYY-MM-DD format; no future dates",
            ],
            [
                "Input",
                "Fill TRADE FLOWS and reimport to recalculate. Value columns are "
                "INR, not crore",
            ],
            [
                "Holdings",
                "Quarterly holding changes, current value and shares held are not "
                "trades",
            ],
            [
                "Coverage",
                "Only supplied investors; missing observations remain flagged",
            ],
            [
                "Disclosure-only imports",
                "A zero side means no matching trade in the supplied disclosures, "
                "not proof of zero undisclosed trading",
            ],
            [
                "Historical use",
                "Current data cannot be applied as signals before publication",
            ],
            [
                "Symbols",
                "Use verified NSE mappings; unmapped names cannot enter technical "
                "scans",
            ],
            [
                "Execution",
                "Signals do not activate broker trading or bypass existing risk "
                "controls",
            ],
        ],
    )
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def bootstrap_from_environment(repository):
    """Optional private seed, deduplicated by digest, never logged or committed."""
    import base64
    import os

    value = os.getenv("TRENDFORGE_BIG_SHARK_WORKBOOK_B64", "")
    if not value:
        return
    if len(value) > MAX_WORKBOOK_BYTES * 2:
        raise ValueError("Private portfolio seed is too large.")
    snapshot = read_portfolio(base64.b64decode(value, validate=True))
    with _BOOTSTRAP_LOCK:
        if not repository.has_source(snapshot["source_sha256"]):
            repository.save(snapshot)


def serialise(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
