"""Offline secret gate for current Git files and complete HEAD history.

Reports contain detector fingerprints and locations, never matched values.
Reviewed exceptions bind an exact source/path/detector/fingerprint tuple.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from importlib import metadata
from pathlib import Path
from typing import Any

TOOL_VERSION = "1.5.0"
MAX_FILE_BYTES = 20_000_000
_OID = re.compile(rb"[0-9a-f]{40}(?:[0-9a-f]{24})?")
_RAW = re.compile(rb":[0-7]{6} ([0-7]{6}) [0-9a-f]+ ([0-9a-f]+) [AMT]")


class ScanError(RuntimeError):
    """Fixed diagnostic code, without command output or matched content."""

    def __init__(self, code: str, path: str | None = None) -> None:
        super().__init__(code)
        self.path = path


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL, timeout=60
        )
    except (OSError, subprocess.SubprocessError):
        raise ScanError("git_command_failed") from None


def _text(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise ScanError("file_size_limit_exceeded")
    if b"\0" in data:
        raise ScanError("binary_content_not_supported")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        raise ScanError("non_utf8_content_not_supported") from None


def _history_versions(root: Path) -> list[dict[str, str]]:
    if _git(root, "rev-parse", "--is-shallow-repository").strip() != b"false":
        raise ScanError("complete_history_required")
    tokens = _git(
        root,
        "log",
        "HEAD",
        "--root",
        "-m",
        "--format=%H%x00",
        "--raw",
        "-z",
        "--no-renames",
        "--no-abbrev",
        "--diff-filter=AMT",
    ).split(b"\0")
    versions = {}
    commit = ""
    index = 0
    while index < len(tokens):
        token = tokens[index].strip(b"\n")
        index += 1
        if not token:
            continue
        if _OID.fullmatch(token):
            commit = token.decode("ascii")
            continue
        match = _RAW.fullmatch(token)
        if not match or index >= len(tokens) or not commit:
            raise ScanError("invalid_git_history_record")
        path = tokens[index].decode("utf-8")
        index += 1
        mode, oid = (part.decode("ascii") for part in match.groups())
        if mode not in {"100644", "100755"}:
            raise ScanError("unsupported_git_file_mode", path)
        versions.setdefault((path, oid), {"path": path, "blob": oid, "commit": commit})
    return list(versions.values())


def _blobs(root: Path, identifiers: set[str]) -> dict[str, bytes]:
    blobs = {}
    try:
        with subprocess.Popen(
            ["git", "-C", str(root), "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        ) as process:
            assert process.stdin is not None and process.stdout is not None
            for oid in sorted(identifiers):
                process.stdin.write((oid + "\n").encode("ascii"))
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3 or header[1] != b"blob":
                    raise ScanError("history_blob_unavailable")
                size = int(header[2])
                if size > MAX_FILE_BYTES:
                    raise ScanError("file_size_limit_exceeded")
                data = process.stdout.read(size)
                if len(data) != size or process.stdout.read(1) != b"\n":
                    raise ScanError("history_blob_incomplete")
                blobs[oid] = data
            process.stdin.close()
            if process.wait(timeout=30):
                raise ScanError("history_blob_read_failed")
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ScanError("history_blob_read_failed") from None
    return blobs


@contextmanager
def _detector():
    try:
        if metadata.version("detect-secrets") != TOOL_VERSION:
            raise ScanError("scanner_version_mismatch")
        from detect_secrets.core.scan import scan_file
        from detect_secrets.settings import default_settings
    except ImportError:
        raise ScanError("scanner_not_installed") from None
    logger = logging.getLogger("detect-secrets")
    disabled = logger.disabled
    logger.disabled = True
    try:
        with default_settings() as settings:
            # Exceptions live in the reviewed manifest, never inline pragmas or
            # whole-file heuristics. No network verification filter is enabled.
            settings.disable_filters(
                "detect_secrets.filters.allowlist.is_line_allowlisted",
                "detect_secrets.filters.heuristic.is_indirect_reference",
                "detect_secrets.filters.heuristic.is_lock_file",
                "detect_secrets.filters.heuristic.is_swagger_file",
            )
            yield scan_file
    finally:
        logger.disabled = disabled


def _scan_content(scan_file: Any, path: str, data: bytes) -> list[dict[str, Any]]:
    try:
        _text(data)
    except ScanError as exc:
        exc.path = path
        raise
    with tempfile.NamedTemporaryFile(suffix="-" + Path(path).name) as temporary:
        temporary.write(data)
        temporary.flush()
        findings = []
        for secret in scan_file(temporary.name):
            # Some upstream detectors return only a matching prefix/header:
            # GitHubTokenDetector 1.5.0 hashes "ghp", not the entire token.
            # Bind such findings to all file bytes so rotation or a changed
            # private-key body cannot inherit an exception for an old value.
            if secret.type in {"Secret Keyword", "Basic Auth Credentials"}:
                fingerprint = "sha1:" + secret.secret_hash
            else:
                fingerprint = "sha256:" + hashlib.sha256(data).hexdigest()
            findings.append(
                {
                    "path": path,
                    "line": secret.line_number,
                    "type": secret.type,
                    "fingerprint": fingerprint,
                }
            )
        return findings


def _reviews(path: Path) -> dict[str, dict[tuple[str, str, str], str]]:
    if not path.exists():
        return {"current": {}, "history": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != 1 or set(raw) != {"version", "current", "history"}:
            raise ValueError
        result = {}
        for source in ("current", "history"):
            result[source] = {}
            for entry in raw[source]:
                if set(entry) != {"path", "type", "fingerprint", "reason"}:
                    raise ValueError
                if not all(
                    isinstance(value, str) and value for value in entry.values()
                ):
                    raise ValueError
                if not re.fullmatch(
                    r"sha1:[a-f0-9]{40}|sha256:[a-f0-9]{64}", entry["fingerprint"]
                ):
                    raise ValueError
                key = (entry["path"], entry["type"], entry["fingerprint"])
                if key in result[source]:
                    raise ValueError
                result[source][key] = entry["reason"]
        return result
    except (OSError, ValueError, TypeError, AttributeError):
        raise ScanError("invalid_review_manifest") from None


def scan_repository(root: Path, review_file: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "scanner": {
            "name": "detect-secrets",
            "version": TOOL_VERSION,
            "network_verification": False,
        },
        "scope": "current Git files and all commits reachable from HEAD",
        "status": "error",
        "errors": [],
        "current": [],
        "history": [],
        "coverage": {"current_files": 0, "history_versions": 0, "history_blobs": 0},
    }
    try:
        reviews = _reviews(review_file or root / ".secret-scan-reviews.json")
        versions = _history_versions(root)
        blobs = _blobs(root, {version["blob"] for version in versions})
        report["coverage"]["history_blobs"] = len(blobs)
        paths = set(
            _git(
                root, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
            ).split(b"\0")
        ) - {b""}
        deleted = set(_git(root, "ls-files", "-z", "--deleted").split(b"\0"))
        with _detector() as scan_file:
            for raw_path in sorted(paths - deleted):
                path = raw_path.decode("utf-8")
                file = root / path
                if not stat.S_ISREG(file.lstat().st_mode):
                    raise ScanError("unsupported_worktree_file_mode", path)
                report["current"].extend(
                    _scan_content(scan_file, path, file.read_bytes())
                )
                report["coverage"]["current_files"] += 1
            historical = {}
            for version in versions:
                seen = set()
                for finding in _scan_content(
                    scan_file, version["path"], blobs[version["blob"]]
                ):
                    key = (finding["path"], finding["type"], finding["fingerprint"])
                    if key not in historical:
                        historical[key] = {
                            **finding,
                            "example_blob": version["blob"],
                            "example_commit": version["commit"],
                            "versions": 0,
                        }
                    if key not in seen:
                        historical[key]["versions"] += 1
                        seen.add(key)
                report["coverage"]["history_versions"] += 1
            report["history"] = list(historical.values())
        for source in ("current", "history"):
            for finding in report[source]:
                key = (finding["path"], finding["type"], finding["fingerprint"])
                finding["reviewed"] = key in reviews[source]
        report["unreviewed"] = sum(
            not finding["reviewed"]
            for source in ("current", "history")
            for finding in report[source]
        )
        report["status"] = "findings" if report["unreviewed"] else "pass"
    except ScanError as exc:
        report["errors"].append(str(exc))
        if exc.path:
            report["failed_path"] = exc.path
    except Exception:
        # Scanner/library failures must not print possibly sensitive exceptions.
        report["errors"].append("secret_scan_failed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output-dir", type=Path, default=Path("security-reports"))
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args()
    report = scan_repository(args.root.resolve(), args.review_file)
    try:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "secret-scan.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    except OSError:
        print("Secret scan report could not be written")
        return 2
    summary = {key: report[key] for key in ("status", "coverage", "errors")}
    summary["unreviewed"] = report.get("unreviewed")
    if "failed_path" in report:
        summary["failed_path"] = report["failed_path"]
    print(json.dumps(summary))
    if report["status"] == "error":
        return 2
    return 1 if report["status"] == "findings" else 0


if __name__ == "__main__":
    raise SystemExit(main())
