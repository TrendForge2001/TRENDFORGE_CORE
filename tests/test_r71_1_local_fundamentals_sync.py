"""R71.1 local-first preparation contracts: offline, no production writes."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3

import pytest

from core.database import initialize_database
from scripts.r71_local_fundamentals_sync import (
    file_sha256, manifest_verify, prepare, preview_completion, preview_gate,
    source_db, verified_universe,
)


def universe_csv(path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Company Name", "Symbol", "Series"])
        writer.writerow(["AAA Limited", "AAA", "EQ"])
        for number in range(1, 500):
            writer.writerow([f"Name{number}", f"SYM{number:04}", "EQ"])
    return file_sha256(path)


def completion_csv(path):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "Symbol", "ROCE", "Completion Source Type",
            "Completion Source", "Completion Source Ref", "Completion As Of",
        ])
        writer.writeheader()
        writer.writerow({
            "Symbol": "AAA", "ROCE": "19.2",
            "Completion Source Type": "EXCHANGE_FILING",
            "Completion Source": "Verified annual filing",
            "Completion Source Ref": "https://example.org/source",
            "Completion As Of": "2026-10-17",
        })


def source_database(path):
    initialize_database(str(path))
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO fundamentals (symbol, source, as_of) VALUES (?, ?, ?)",
            ("AAA", "fixture", "2026-10-17"),
        )


def test_preview_preserves_database(tmp_path):
    db = tmp_path / "trendforge.db"
    source_database(db)
    universe_file, completion = tmp_path / "nifty500.csv", tmp_path / "completion.csv"
    sha = universe_csv(universe_file)
    completion_csv(completion)
    universe, metadata = verified_universe(universe_file, expected_sha256=sha)
    assert metadata["count"] == 500
    assert metadata["pin_verified"]
    gate = preview_gate(preview_completion(source_db(db), completion, universe))
    assert gate["status"] == "passed"
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT roce FROM fundamentals WHERE symbol='AAA'"
        ).fetchone()[0] is None


def test_prepare_writes_backup_copy_bundle_not_source(tmp_path):
    db = tmp_path / "trendforge.db"
    source_database(db)
    constituents, completion = tmp_path / "nifty500.csv", tmp_path / "completion.csv"
    sha = universe_csv(constituents)
    completion_csv(completion)
    output = tmp_path / "handoff"
    result = prepare(
        db_path=str(db), completion_file=str(completion),
        universe_file=str(constituents), universe_sha256=sha,
        output_dir=str(output),
    )
    assert result["status"] == "prepared_local_only"
    assert result["manifest"]["cloud_activation"] == "NOT_PERFORMED"
    for name in ("original-backup.db", "completed-working.db",
                 "fundamentals-bootstrap.json", "handoff-manifest.json"):
        assert (output / name).is_file()
    with sqlite3.connect(db) as connection:
        assert connection.execute(
            "SELECT roce FROM fundamentals WHERE symbol='AAA'"
        ).fetchone()[0] is None
    with sqlite3.connect(output / "completed-working.db") as connection:
        assert connection.execute(
            "SELECT roce FROM fundamentals WHERE symbol='AAA'"
        ).fetchone()[0] == pytest.approx(19.2)
    with pytest.raises(FileExistsError):
        prepare(
            db_path=str(db), completion_file=str(completion),
            universe_file=str(constituents), universe_sha256=sha,
            output_dir=str(output),
        )


def test_rejects_bad_universe_pin_and_missing_source(tmp_path):
    u = tmp_path / "nifty.csv"
    actual = universe_csv(u)
    with pytest.raises(ValueError, match="SHA256"):
        verified_universe(u, expected_sha256="0" * 64)
    with pytest.raises(ValueError, match="pinned"):
        prepare(
            db_path=str(tmp_path / "not-there.db"),
            completion_file=str(tmp_path / "none.csv"),
            universe_file=str(u), universe_sha256="",
            output_dir=str(tmp_path / "handoff"),
        )
    assert actual != "0" * 64


def test_cloud_verification_rejects_nonempty_skip_and_checks_pinned_file(tmp_path):
    db = tmp_path / "trendforge.db"
    source_database(db)
    constituents, completion = tmp_path / "nifty.csv", tmp_path / "completion.csv"
    sha = universe_csv(constituents)
    completion_csv(completion)
    output = tmp_path / "package"
    result = prepare(
        db_path=str(db), completion_file=str(completion),
        universe_file=str(constituents), universe_sha256=sha,
        output_dir=str(output),
    )
    health_file = tmp_path / "health.json"
    health_file.write_text(json.dumps({
        "bootstrap": {
            "status": "skipped_nonempty",
            "database_records": 11,
        },
        "storage": {"status": "ephemeral_or_unverified"},
    }), encoding="utf-8")
    report = manifest_verify(output / "handoff-manifest.json", health_file)
    assert report["status"] == "not_verified"
    assert report["cloud_bootstrap_status"] == "skipped_nonempty"
    manifest = result["manifest"]
    health_file.write_text(json.dumps({
        "bootstrap": {
            "status": "applied",
            "file_sha256": manifest["bundle"]["sha256"],
            "pinned_sha256_verified": True,
            "fundamental_records": manifest["bundle"]["fundamental_records"],
        },
        "storage": {"status": "ephemeral_or_unverified"},
    }), encoding="utf-8")
    assert manifest_verify(output / "handoff-manifest.json", health_file)["status"] == "verified"
    (output / "fundamentals-bootstrap.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        manifest_verify(output / "handoff-manifest.json", health_file)


def test_quality_gate_blocks_unknown_and_empty():
    assert preview_gate({"eligible": 1, "invalid": 1})["status"] == "blocked"
    assert preview_gate({"eligible": 1, "overwrite_attempts": 1})["status"] == "blocked"
    assert preview_gate({"eligible": 0})["status"] == "blocked"
