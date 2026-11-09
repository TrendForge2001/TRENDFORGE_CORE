"""Immutable, checksummed report files stored next to the PC data directory."""

import base64
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from services.research_report import csv_report

MAX_BATCH_BYTES = 64 * 1024 * 1024


def validate_batch(batch):
    if not isinstance(batch, dict):
        raise ValueError("Invalid report backup")
    batch_id = batch.get("batch_id")
    if not isinstance(batch_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.:-]{1,120}", batch_id
    ):
        raise ValueError("Invalid report batch identifier")
    report = batch.get("report")
    if (
        batch.get("status") != "completed"
        or batch.get("kind") not in {"scan", "backtest"}
        or not isinstance(report, dict)
        or report.get("run_id") != batch_id
    ):
        raise ValueError("Only completed research reports can be archived")
    expected_type = (
        "historical_backtest_exit_fills"
        if batch["kind"] == "backtest"
        else "scanner_indicator_snapshot"
    )
    if report.get("partition_scope") == "independent_portfolios":
        expected_type = "research_partition_manifest"
        rows = report.get("rows")
        if (
            not isinstance(rows, list)
            or not rows
            or len(rows) != report.get("partition_count")
            or not all(
                isinstance(row, dict)
                and row.get("status") == "completed"
                and isinstance(row.get("batch_id"), str)
                for row in rows
            )
            or len({row["batch_id"] for row in rows}) != len(rows)
        ):
            raise ValueError("Incomplete partition manifest")
    if (
        report.get("report_type") != expected_type
        or not isinstance(report.get("rows"), list)
        or not all(isinstance(row, dict) for row in report["rows"])
        or not isinstance(report.get("columns"), list)
        or not all(isinstance(column, str) for column in report["columns"])
        or not isinstance(report.get("csv"), str)
    ):
        raise ValueError("Invalid generated report")
    csv_bytes = report["csv"].encode("utf-8-sig")
    if hashlib.sha256(csv_bytes).hexdigest() != report.get("sha256"):
        raise ValueError("Report CSV checksum mismatch")
    if csv_report(report["rows"], report["columns"]) != report["csv"]:
        raise ValueError("Report rows do not match the CSV")
    workbook = None
    if report.get("xlsx_base64"):
        workbook = base64.b64decode(report["xlsx_base64"], validate=True)
        if hashlib.sha256(workbook).hexdigest() != report.get("xlsx_sha256"):
            raise ValueError("Report Excel checksum mismatch")
    return csv_bytes, workbook


class ResearchArchive:
    def __init__(self, root):
        self.root = Path(root)

    @classmethod
    def for_database(cls, database_path):
        path = Path(database_path).resolve()
        root = path.parent.parent if path.parent.name == "database" else path.parent
        return cls(root / "reports" / "research")

    def _target(self, batch_id):
        return self.root / hashlib.sha256(batch_id.encode()).hexdigest()

    def save(self, batch):
        csv_bytes, workbook = validate_batch(batch)
        encoded = json.dumps(batch, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_BATCH_BYTES:
            raise ValueError("Report backup exceeds the maximum size")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        destination = self._target(batch["batch_id"])
        if destination.exists():
            previous = self.read(destination / "batch.json")
            if previous["report"] != batch["report"]:
                raise ValueError("A different report already uses this batch ID")
            return destination
        staging = Path(tempfile.mkdtemp(prefix=".partial-", dir=self.root))
        try:
            files = {"report.csv": csv_bytes, "batch.json": encoded}
            if workbook is not None:
                files["report.xlsx"] = workbook
            for name, data in files.items():
                with (staging / name).open("xb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            staging.rename(destination)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return destination

    @staticmethod
    def read(path):
        path = Path(path)
        if path.stat().st_size > MAX_BATCH_BYTES:
            raise ValueError("Report backup exceeds the maximum size")
        batch = json.loads(path.read_text(encoding="utf-8"))
        validate_batch(batch)
        return batch

    def restore(self, repository):
        restored, invalid = 0, 0
        if not self.root.is_dir():
            return {"restored": restored, "invalid": invalid}
        for path in sorted(self.root.glob("*/batch.json")):
            if path.parent.name.startswith(".partial-"):
                continue
            try:
                batch = self.read(path)
                existing = repository.get(batch["batch_id"])
                if (
                    existing is not None
                    and existing.get("error_code") == "operator_cancelled"
                ):
                    # A last-millisecond archive write must not undo explicit
                    # cancellation on the next boot. Never replay the job.
                    continue
                if existing is not None and existing["status"] == "completed":
                    if existing["report"] != batch["report"]:
                        raise ValueError("Backup conflicts with an existing report")
                    continue
                request = batch["request"]
                if (
                    not isinstance(request.get("symbols"), list)
                    or not request["symbols"]
                ):
                    raise ValueError("Backup has no recorded stock selection")
                if existing is None:
                    repository.create(batch["batch_id"], batch["kind"], request)
                    repository.start(batch["batch_id"])
                elif existing["request"] == request and existing["report"] is None:
                    repository.db.execute(
                        "UPDATE research_batches SET status='running',error_code=NULL "
                        "WHERE batch_id=? AND status IN ('failed','interrupted')",
                        (batch["batch_id"],),
                    )
                else:
                    raise ValueError("Backup conflicts with the recorded request")
                repository.finish(batch["batch_id"], batch["report"])
                repository.db.execute(
                    "UPDATE research_batches SET created_at=?,started_at=?,"
                    "finished_at=?,updated_at=? WHERE batch_id=?",
                    (
                        batch["created_at"],
                        batch.get("started_at"),
                        batch.get("finished_at"),
                        batch.get("updated_at", batch.get("finished_at")),
                        batch["batch_id"],
                    ),
                )
                restored += 1
            except (OSError, ValueError, KeyError, TypeError):
                invalid += 1
        return {"restored": restored, "invalid": invalid}
