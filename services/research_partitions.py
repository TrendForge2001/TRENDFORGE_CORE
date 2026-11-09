"""Small durable indexes over independent, sequential research portfolios."""

import base64
import hashlib
from datetime import UTC, datetime

from scanner.strategy_registry import REGISTRY_VERSION
from services.research_report import csv_report, excel_report


def partition_manifest(batch_id, kind, request, children):
    rows = []
    for child in children:
        if child["status"] != "completed" or not child.get("report"):
            raise ValueError("A partition did not complete")
        report = child["report"]
        rows.append(
            {
                "batch_id": child["batch_id"],
                "strategy_id": child["strategy_id"],
                "stock_count": child["requested_symbols"],
                "status": child["status"],
                "trade_count": report.get("metrics", {}).get("total_trades"),
                "net_pnl": report.get("metrics", {}).get("net_profit"),
                "report_sha256": report["sha256"],
            }
        )
    if not rows:
        raise ValueError("A partition index cannot be empty")
    columns = list(rows[0])
    content = csv_report(rows, columns)
    report = {
        "schema_version": 2,
        "run_id": batch_id,
        "strategy_id": request["strategy_id"],
        "horizon": request["horizon"],
        "stock_list": request["stock_list"],
        "mode": request["settings"]["mode"],
        "period": request["settings"]["period"],
        "registry_version": REGISTRY_VERSION,
        "report_type": "research_partition_manifest",
        "partition_scope": "independent_portfolios",
        "partition_count": len(rows),
        "generated_at": datetime.now(UTC).isoformat(),
        "filename": f"trendforge_{kind}_{batch_id}_index.csv",
        "rows": rows,
        "columns": columns,
        "csv": content,
        "sha256": hashlib.sha256(content.encode("utf-8-sig")).hexdigest(),
        "parameters": {
            "scope": "Independent stock/strategy accounts; do not sum P&L or returns",
            "parent_batch": batch_id,
        },
    }
    workbook = excel_report(
        rows,
        columns,
        {
            key: report[key]
            for key in (
                "run_id",
                "partition_scope",
                "partition_count",
                "parameters",
                "generated_at",
            )
        },
        kind=kind,
        sheet_name="Batch index",
    )
    report["xlsx_base64"] = base64.b64encode(workbook).decode("ascii")
    report["xlsx_sha256"] = hashlib.sha256(workbook).hexdigest()
    return report
