"""R71.1: offline-first fundamental completion and cloud bootstrap preparation.

All actions are deliberately local. 'preview' never changes a DB; 'prepare'
makes a verified SQLite backup, applies to an isolated copy, and packages a
pinned startup bundle. No action contacts or writes to Render or production.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.database import database_health
from services.bootstrap_format import read_verified_bundle
from services.fundamental_bootstrap_service import FundamentalBootstrapService
from services.fundamental_completion_service import FundamentalCompletionService
from services.local_storage_service import backup_database, verify_database
from universe.nifty500 import Nifty500Universe

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def source_db(path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise FileNotFoundError(f"Local SQLite database does not exist: {target}")
    health = database_health(str(target))
    if health.get("status") != "ready":
        raise ValueError(f"Local database is not ready: {health}")
    return target


def verified_universe(path: str | Path, *, expected_sha256: str | None):
    csv_path = Path(path).expanduser().resolve()
    if not csv_path.is_file() or csv_path.suffix.lower() != ".csv":
        raise ValueError("Supply an existing canonical NIFTY 500 constituents CSV")
    raw_sha = file_sha256(csv_path)
    if expected_sha256 is not None:
        pin = expected_sha256.strip().lower()
        if not SHA256.fullmatch(pin) or pin != raw_sha:
            raise ValueError("Constituent CSV SHA256 does not match the supplied pin")
    rows = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "symbol" not in {
            str(name).strip().lower() for name in reader.fieldnames
        }:
            raise ValueError("Constituent CSV requires a Symbol column")
        for row in reader:
            fields = {str(k or "").strip().lower(): v for k, v in row.items()}
            symbol = str(fields.get("symbol") or "").strip()
            if not symbol:
                raise ValueError("Constituent CSV contains an empty Symbol")
            if symbol.upper().startswith("DUMMY"):
                raise ValueError("Constituent CSV contains placeholder members")
            rows.append({
                "symbol": symbol,
                "name": fields.get("company name") or fields.get("name") or symbol,
                "series": fields.get("series") or "",
                "isin": fields.get("isin code") or "",
            })
    universe = Nifty500Universe(max_age_seconds=86400)
    universe.load(rows)
    report = universe.report()
    if report["status"] != "healthy" or len(rows) != report["count"]:
        raise ValueError(f"Invalid constituent set: {report}")
    return universe, {
        "file": str(csv_path),
        "sha256": raw_sha,
        "count": report["count"],
        "pin_verified": expected_sha256 is not None,
    }


def preview_completion(db: Path, completion: Path, universe: Nifty500Universe):
    if not completion.is_file() or completion.suffix.lower() not in {".csv", ".xlsx", ".xlsm"}:
        raise ValueError("Completion must be an existing CSV/XLSX/XLSM file")
    service = FundamentalCompletionService(
        db_path=str(db), universe=universe
    )
    try:
        return service.process_file(
            completion,
            apply=False,
            sheet_name="Completion" if completion.suffix.lower() != ".csv" else None,
            source_file_name=completion.name,
        )
    finally:
        service.close()


def preview_gate(report: dict[str, Any]) -> dict[str, Any]:
    blockers = {
        key: int(report.get(key) or 0)
        for key in ("unknown_symbols", "invalid", "overwrite_attempts", "evidence_failures")
    }
    eligible = int(report.get("eligible") or 0)
    if not eligible:
        blockers["no_eligible_rows"] = 1
    return {
        "status": "passed" if not any(blockers.values()) else "blocked",
        "eligible": eligible,
        "completed_records": int(report.get("completed_records") or 0),
        "rows_read": int(report.get("rows_read") or 0),
        "blockers": blockers,
    }


def manifest_verify(manifest_path: Path, health_json_path: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "R71.1":
        raise ValueError("Unsupported handoff manifest")
    bundle = manifest_path.parent / manifest["bundle"]["file"]
    expected = manifest["bundle"]["sha256"]
    read_verified_bundle(bundle, expected_file_sha256=expected)
    health = json.loads(health_json_path.read_text(encoding="utf-8"))
    bootstrap = health.get("bootstrap") or {}
    status = bootstrap.get("status")
    observed = bootstrap.get("file_sha256")
    expected_records = manifest["bundle"]["fundamental_records"]
    db_rows = (health.get("database") or {}).get("fundamental_records")
    # /production/health does not guarantee an exposed fundamental row count;
    # successful bootstrap's own evidence is used when available.
    verified = (
        status == "applied"
        and observed == expected
        and bootstrap.get("pinned_sha256_verified") is True
        and bootstrap.get("fundamental_records") == expected_records
    )
    return {
        "status": "verified" if verified else "not_verified",
        "cloud_bootstrap_status": status,
        "expected_sha256": expected,
        "observed_sha256": observed,
        "expected_fundamental_records": expected_records,
        "observed_bootstrap_records": bootstrap.get("fundamental_records"),
        "database_reported_records": db_rows,
        "production_storage": (health.get("storage") or {}).get("status"),
        "note": (
            "Startup bootstrap skips a nonempty database; a new Render secret file "
            "does not update existing records. Production cutover requires "
            "separate approval, backup and rollback verification."
        ),
    }


def prepare(
    *,
    db_path: str,
    completion_file: str,
    universe_file: str,
    universe_sha256: str,
    output_dir: str,
) -> dict[str, Any]:
    if not universe_sha256:
        raise ValueError("prepare requires a pinned --universe-sha256")
    source = source_db(db_path)
    completion = Path(completion_file).expanduser().resolve()
    universe, universe_meta = verified_universe(
        universe_file, expected_sha256=universe_sha256
    )
    report = preview_completion(source, completion, universe)
    gate = preview_gate(report)
    if gate["status"] != "passed":
        raise ValueError(f"Completion preview rejected: {gate}")
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory already exists: {destination}")
    if destination == source.parent or source in destination.parents:
        raise ValueError("Output must be separate from the source database")
    destination.mkdir(parents=True)
    backup = destination / "original-backup.db"
    working = destination / "completed-working.db"
    try:
        backup_meta = backup_database(source, backup)
        backup_database(backup, working)
        service = FundamentalCompletionService(
            db_path=str(working), universe=universe
        )
        try:
            applied = service.process_file(
                completion, apply=True,
                sheet_name="Completion" if completion.suffix.lower() != ".csv" else None,
                source_file_name=completion.name,
            )
        finally:
            service.close()
        if int(applied.get("applied_records") or 0) < 1:
            raise ValueError("No completion records applied to the isolated database")
        if verify_database(working).get("status") != "ok":
            raise ValueError("Working SQLite integrity verification failed")
        bundle_service = FundamentalBootstrapService(db_path=str(working))
        try:
            bundle_meta = bundle_service.export_bundle(destination / "fundamentals-bootstrap.json")
            verified = bundle_service.verify_bundle(
                destination / "fundamentals-bootstrap.json",
                expected_file_sha256=bundle_meta["file_sha256"],
            )
        finally:
            bundle_service.close()
        manifest = {
            "schema_version": "R71.1",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_database": str(source),
            "source_preserved": True,
            "source_backup": {
                "file": backup.name,
                "sha256": backup_meta["sha256"],
            },
            "working_database": {
                "file": working.name,
                "integrity": "ok",
            },
            "constituents": universe_meta,
            "completion": {
                "file": str(completion),
                "sha256": file_sha256(completion),
                "preview_gate": gate,
                "applied_records": applied["applied_records"],
                "applied_fields": applied["applied_fields"],
                "evidence_records": applied["evidence_records"],
            },
            "bundle": {
                "file": "fundamentals-bootstrap.json",
                "sha256": verified["file_sha256"],
                "payload_sha256": verified["payload_sha256"],
                "fundamental_records": verified["fundamental_records"],
                "evidence_records": verified["evidence_records"],
                "field_update_records": verified["field_update_records"],
                "size_bytes": verified["size_bytes"],
            },
            "cloud_activation": "NOT_PERFORMED",
            "cloud_cutover_requires_approval": True,
        }
        (destination / "handoff-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        return {"status": "prepared_local_only", "output_dir": str(destination),
                "manifest": manifest}
    except Exception:
        # Preserve backup/working evidence for diagnosis: never delete the
        # source or overwrite any existing output directory.
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare vetted local fundamental bootstrap without cloud writes"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "prepare"):
        sub = commands.add_parser(name)
        sub.add_argument("--db-path", required=True)
        sub.add_argument("--completion", required=True)
        sub.add_argument("--universe-file", required=True)
        sub.add_argument("--universe-sha256")
        if name == "prepare":
            sub.add_argument("--out-dir", required=True)
    check = commands.add_parser("verify-cloud")
    check.add_argument("--manifest", required=True)
    check.add_argument("--production-health-json", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify-cloud":
            result = manifest_verify(
                Path(args.manifest), Path(args.production_health_json)
            )
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "verified" else 2
        if args.command == "prepare":
            result = prepare(
                db_path=args.db_path, completion_file=args.completion,
                universe_file=args.universe_file,
                universe_sha256=args.universe_sha256,
                output_dir=args.out_dir,
            )
        else:
            db = source_db(args.db_path)
            universe, meta = verified_universe(
                args.universe_file, expected_sha256=args.universe_sha256
            )
            report = preview_completion(
                db, Path(args.completion).expanduser().resolve(), universe
            )
            result = {
                "status": "preview_only",
                "constituents": meta,
                "preview_gate": preview_gate(report),
                "report": report,
                "source_database_preserved": True,
            }
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("preview_gate", {}).get("status") != "blocked" else 2
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
