"""Recover completed scan evidence from an owner-supplied Excel snapshot.

Workbook cells are data. No macros, formulas or document instructions execute.
An optional operator-managed seed survives an ephemeral service replacement.
It contains completed evidence only and cannot queue or execute a trade.
"""

import base64
import gzip
import hashlib
import io
import json
import logging
import os
import zipfile

from services.research_archive import validate_batch
from services.research_report import csv_report

SEED_ENV = "TRENDFORGE_REPORT_RECOVERY_GZIP_B64"
MAX_SEED_BYTES = 4 * 1024 * 1024


def restore_configured_snapshot():
    """Restore before the website opens; no provider or trading construction."""
    if not os.getenv(SEED_ENV):
        return "not_configured"
    from database.database import Database
    from database.repositories.research_batches import ResearchBatchRepository
    from services.research_storage import report_archive

    database = Database()
    try:
        status = recover_seed(
            ResearchBatchRepository(database), report_archive(str(database.db_path))
        )
        logging.getLogger(__name__).info("research_snapshot_recovery status=%s", status)
        return status
    finally:
        database.close()


def scan_workbook_batch(content):
    from openpyxl import load_workbook

    with zipfile.ZipFile(io.BytesIO(content)) as package:
        if (
            len(package.infolist()) > 30
            or sum(item.file_size for item in package.infolist()) > MAX_SEED_BYTES
        ):
            raise ValueError("Scanner workbook exceeds recovery limits")
    workbook = load_workbook(
        io.BytesIO(content), read_only=True, data_only=True, keep_links=False
    )
    try:
        if workbook.sheetnames != ["Scanner evidence", "Run details"]:
            raise ValueError("Choose a Trendforge scanner evidence workbook")
        details = dict(list(workbook["Run details"].values)[1:])
        if details.get("report_type") != "scanner_indicator_snapshot":
            raise ValueError("Only scanner snapshots can be recovered from Excel")
        values = workbook["Scanner evidence"].values
        columns = list(next(values))
        if len(columns) != len(set(columns)) or not all(
            isinstance(column, str) for column in columns
        ):
            raise ValueError("Invalid scanner evidence columns")
        rows = [dict(zip(columns, row, strict=True)) for row in values]
        if not rows or len(rows) > 1000:
            raise ValueError("Invalid scanner evidence row count")
        provenance = {
            key: details[key]
            for key in (
                "run_id",
                "strategy_id",
                "horizon",
                "stock_list",
                "mode",
                "period",
                "registry_version",
                "report_type",
            )
        }
        if any(row.get("run_id") != provenance["run_id"] for row in rows):
            raise ValueError("Mixed scanner batches cannot be recovered")
        csv = csv_report(rows, columns)
        report = {
            "schema_version": 2,
            **provenance,
            "generated_at": details["generated_at"],
            "filename": f"trendforge_scan_{provenance['run_id']}.csv",
            "rows": rows,
            "columns": columns,
            "csv": csv,
            "sha256": hashlib.sha256(csv.encode("utf-8-sig")).hexdigest(),
            "xlsx_base64": base64.b64encode(content).decode("ascii"),
            "xlsx_sha256": hashlib.sha256(content).hexdigest(),
            "recovery": {
                "source": "uploaded_excel_snapshot",
                "original_csv_sha256": details.get("sha256"),
                "precision": "Excel-stored cell precision; original workbook preserved",
            },
            **{
                key: json.loads(details.get(key) or "{}")
                for key in (
                    "metrics",
                    "parameters",
                    "engine",
                    "history_alignment",
                    "scanner_counts",
                )
            },
        }
        symbols = list(dict.fromkeys(row["symbol"] for row in rows))
        batch = {
            "batch_id": provenance["run_id"],
            "kind": "scan",
            "status": "completed",
            "horizon": provenance["horizon"],
            "strategy_id": provenance["strategy_id"],
            "stock_list": provenance["stock_list"],
            "phase": "completed",
            "requested_symbols": len(symbols),
            "completed_symbols": len(symbols),
            "created_at": details["generated_at"],
            "finished_at": details["generated_at"],
            "updated_at": details["generated_at"],
            "report": report,
            "request": {**provenance, "symbols": symbols},
        }
        validate_batch(batch)
        return batch
    finally:
        workbook.close()


def recover_seed(repository, archive=None):
    encoded = os.getenv(SEED_ENV, "")
    if not encoded:
        return "not_configured"
    try:
        if len(encoded) > MAX_SEED_BYTES:
            raise ValueError("Recovery seed is too large")
        with gzip.GzipFile(
            fileobj=io.BytesIO(base64.b64decode(encoded, validate=True))
        ) as stream:
            decoded = stream.read(MAX_SEED_BYTES + 1)
        if len(decoded) > MAX_SEED_BYTES:
            raise ValueError("Recovery seed is too large")
        batch = json.loads(decoded)
        if batch.get("format") == "scanner_workbook_v1":
            batch = scan_workbook_batch(
                base64.b64decode(batch["xlsx_base64"], validate=True)
            )
        validate_batch(batch)
        current = repository.get(batch["batch_id"])
        if current is not None:
            return (
                "already_present"
                if current["report"] == batch["report"]
                else "conflict"
            )
        if archive is not None:
            archive.save(batch)
        repository.restore_completed(batch)
        return "restored"
    except Exception:
        return "invalid"
