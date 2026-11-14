"""Automatic server-side report generation with spreadsheet-safe CSV output."""

import base64
import csv
import hashlib
import io
import json
from datetime import UTC, datetime

from scanner.portfolio_policy import evidence_rows
from scanner.strategy_registry import REGISTRY_VERSION
from services.execution_report import trade_report


def spreadsheet_value(value):
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, allow_nan=False)
    if isinstance(value, str) and (
        value.startswith(("\t", "\r", "\n"))
        or value.lstrip().startswith(("=", "+", "-", "@"))
    ):
        return "'" + value
    return value


def csv_report(rows, columns):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: spreadsheet_value(value) for key, value in row.items()})
    return stream.getvalue()


def excel_report(rows, columns, metadata, *, kind, sheet_name=None, extra_tables=None):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook(write_only=True)
    tables = {
        sheet_name
        or ("Trade entries and exits" if kind == "backtest" else "Scanner evidence"): (
            columns,
            [[row.get(column) for column in columns] for row in rows],
        ),
        "Run details": (["Field", "Value"], list(metadata.items())),
    }
    tables.update(extra_tables or {})
    for name, (headers, values) in tables.items():
        sheet = workbook.create_sheet(name)
        sheet.freeze_panes = "A2"
        header_cells = []
        for value in headers:
            cell = WriteOnlyCell(sheet, value=spreadsheet_value(value))
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(fill_type="solid", fgColor="102E44")
            header_cells.append(cell)
        sheet.append(header_cells)
        for row in values:
            sheet.append([spreadsheet_value(value) for value in row])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def build_report(result, *, kind, horizon=None, stock_list=None, historical=False):
    if kind not in {"scan", "backtest"}:
        raise ValueError("Unknown report type")
    if kind == "backtest":
        frame = trade_report(result, historical=historical)
        rows = frame.to_dict("records")
        positions = {(row["symbol"], row["entry_at"]): row for row in result["trades"]}
        for row in rows:
            position = positions[(row["symbol"], row["entry_at"])]
            row.update(
                entry_signal_at=position.get("entry_signal_at"),
                initial_stoploss=position.get(
                    "initial_stoploss", position.get("stoploss")
                ),
                partial_target=position.get("partial_target"),
                gross_pnl=row["net_pnl"] + row["transaction_costs"],
            )
        columns = list(frame.columns) + [
            "entry_signal_at",
            "initial_stoploss",
            "partial_target",
            "gross_pnl",
        ]
        report_type = "historical_backtest_exit_fills"
    else:
        rows = evidence_rows(
            result["results"], preserve_hold=result.get("interval") == "1wk"
        )
        columns = (
            list(dict.fromkeys(key for row in rows for key in row))
            if rows
            else ["symbol", "signal", "entry", "stoploss"]
        )
        report_type = "scanner_indicator_snapshot"
    provenance = {
        "run_id": result["run_id"],
        "strategy_id": result.get("strategy_id"),
        "horizon": horizon,
        "stock_list": stock_list,
        "mode": result.get("mode"),
        "period": result.get("period"),
        "registry_version": result.get(
            "registry_version", "unrecorded" if historical else REGISTRY_VERSION
        ),
        "report_type": report_type,
    }
    for row in rows:
        row.update(provenance)
    columns += list(provenance)
    content = csv_report(rows, columns)
    report = {
        "schema_version": 2,
        **provenance,
        "generated_at": datetime.now(UTC).isoformat(),
        "filename": f"trendforge_{kind}_{result['run_id']}.csv",
        "rows": rows,
        "columns": columns,
        "csv": content,
        "sha256": hashlib.sha256(content.encode("utf-8-sig")).hexdigest(),
        "metrics": result.get("metrics", {}),
        "parameters": result.get("parameters", {}),
        "scanner_options": result.get("scanner_options", {}),
        "engine": result.get("engine", {}),
        "history_alignment": result.get("history_alignment", {}),
        "scanner_counts": {
            key: result.get(key)
            for key in (
                "requested_symbols",
                "completed_symbols",
                "error_symbols",
                "entry_candidates",
                "armed_setups",
            )
        }
        if kind == "scan"
        else {},
    }
    extra_tables = {}
    if result.get("comparisons"):
        from services.weekly_comparison_report import comparison_tables

        extra_tables = comparison_tables(result)
        for key in (
            "comparisons",
            "comparison_results",
            "equity_curve",
            "terminal_liquidations",
            "allocations",
            "rejected_entries",
            "benchmark",
        ):
            report[key] = result[key]
    workbook = excel_report(
        rows,
        columns,
        {
            key: report[key]
            for key in (
                *provenance,
                "generated_at",
                "parameters",
                "engine",
                "metrics",
                "history_alignment",
                "scanner_counts",
                "sha256",
            )
        },
        kind=kind,
        extra_tables=extra_tables,
    )
    report["xlsx_base64"] = base64.b64encode(workbook).decode("ascii")
    report["xlsx_sha256"] = hashlib.sha256(workbook).hexdigest()
    return report
