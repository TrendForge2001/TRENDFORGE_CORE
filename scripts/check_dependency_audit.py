"""Audit the exact production lock and fail closed on incomplete scanner coverage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from importlib import metadata
from pathlib import Path
from typing import TypedDict, cast

_NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
_VERSION = r"[A-Za-z0-9][A-Za-z0-9.+!_-]*"
_PIN = re.compile(rf"({_NAME})==({_VERSION})")
_ADVISORY = re.compile(r"(?:CVE|GHSA|PYSEC|OSV)-[A-Za-z0-9-]{1,100}")
_TIMEOUT_SECONDS = 300


class VersionMismatch(TypedDict):
    package: str
    expected: str
    reported: str


class Coverage(TypedDict):
    expected_count: int
    reported_count: int
    audited_count: int
    missing: list[str]
    unexpected: list[str]
    duplicates: list[str]
    version_mismatches: list[VersionMismatch]
    skipped: list[str]
    malformed_entries: int


class Finding(TypedDict):
    package: str
    version: str
    id: str
    aliases: list[str]
    fix_versions: list[str]


class AuditSummary(TypedDict):
    schema_version: int
    status: str
    requirements_sha256: str | None
    tool_version: str
    scanner_returncode: int | None
    coverage: Coverage
    findings: list[Finding]
    error_codes: list[str]


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(content: str) -> dict[str, str]:
    expected: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN.fullmatch(line)
        if match is None:
            raise ValueError("requirements_invalid")
        name, version = match.groups()
        name = _normalize(name)
        if name in expected:
            raise ValueError("requirements_invalid")
        expected[name] = version
    if not expected:
        raise ValueError("requirements_invalid")
    return expected


def _object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        fields = cast(dict[object, object], value)
        if all(isinstance(key, str) for key in fields):
            return cast(dict[str, object], fields)
    return None


def _array(value: object) -> list[object] | None:
    return cast(list[object], value) if isinstance(value, list) else None


def _strings(value: object, pattern: str | re.Pattern[str]) -> list[str] | None:
    items = _array(value)
    if items is None:
        return None
    result: list[str] = []
    for item in items:
        if not isinstance(item, str) or re.fullmatch(pattern, item) is None:
            return None
        result.append(item)
    return result


def _coverage(expected: Mapping[str, str]) -> Coverage:
    return {
        "expected_count": len(expected),
        "reported_count": 0,
        "audited_count": 0,
        "missing": sorted(expected),
        "unexpected": [],
        "duplicates": [],
        "version_mismatches": [],
        "skipped": [],
        "malformed_entries": 0,
    }


def review_report(
    report: object, expected: Mapping[str, str]
) -> tuple[Coverage, list[Finding], list[str]]:
    """Validate package coverage and retain only safe, structured advisory fields."""
    coverage = _coverage(expected)
    body = _object(report)
    dependencies = _array(body.get("dependencies")) if body is not None else None
    if dependencies is None:
        return coverage, [], ["report_invalid"]
    coverage["reported_count"] = len(dependencies)
    counts: Counter[str] = Counter()
    audited: set[str] = set()
    skipped: set[str] = set()
    findings: list[Finding] = []
    for item in dependencies:
        dependency = _object(item)
        if dependency is None:
            coverage["malformed_entries"] += 1
            continue
        name, version = dependency.get("name"), dependency.get("version")
        if not isinstance(name, str) or re.fullmatch(_NAME, name) is None:
            coverage["malformed_entries"] += 1
            continue
        name = _normalize(name)
        counts[name] += 1
        if "skip_reason" in dependency:
            skipped.add(name)
        if not isinstance(version, str) or re.fullmatch(_VERSION, version) is None:
            coverage["malformed_entries"] += 1
            continue
        if name in expected and version != expected[name]:
            coverage["version_mismatches"].append(
                {
                    "package": name,
                    "expected": expected[name],
                    "reported": version,
                }
            )
        vulnerabilities = _array(dependency.get("vulns"))
        malformed = vulnerabilities is None
        for value in vulnerabilities or []:
            vulnerability = _object(value)
            if vulnerability is None:
                malformed = True
                continue
            advisory = vulnerability.get("id")
            fixes = _strings(vulnerability.get("fix_versions"), _VERSION)
            aliases = _strings(vulnerability.get("aliases", []), _ADVISORY)
            if (
                not isinstance(advisory, str)
                or _ADVISORY.fullmatch(advisory) is None
                or fixes is None
                or aliases is None
            ):
                malformed = True
                continue
            findings.append(
                {
                    "package": name,
                    "version": version,
                    "id": advisory,
                    "aliases": aliases,
                    "fix_versions": fixes,
                }
            )
        if malformed:
            coverage["malformed_entries"] += 1
        elif name in expected and version == expected[name] and name not in skipped:
            audited.add(name)
    coverage["missing"] = sorted(set(expected) - counts.keys())
    coverage["unexpected"] = sorted(counts.keys() - set(expected))
    coverage["duplicates"] = sorted(name for name, count in counts.items() if count > 1)
    coverage["skipped"] = sorted(skipped)
    coverage["audited_count"] = len(audited - set(coverage["duplicates"]))
    errors = [
        code
        for field, code in (
            ("missing", "coverage_missing"),
            ("unexpected", "coverage_unexpected"),
            ("duplicates", "coverage_duplicate"),
            ("version_mismatches", "coverage_version_mismatch"),
            ("skipped", "coverage_skipped"),
            ("malformed_entries", "report_malformed_dependency"),
        )
        if coverage[field]
    ]
    return coverage, findings, errors


def run_audit(requirements: Path, output_dir: Path) -> int:
    """Run pip-audit once, preserving raw output and writing a reviewed summary."""
    try:
        tool_version = metadata.version("pip-audit")
    except metadata.PackageNotFoundError:
        tool_version = "unavailable"
    summary: AuditSummary = {
        "schema_version": 1,
        "status": "failed",
        "requirements_sha256": None,
        "tool_version": tool_version,
        "scanner_returncode": None,
        "coverage": _coverage({}),
        "findings": [],
        "error_codes": [],
    }
    errors = summary["error_codes"]
    raw_path = output_dir / "pip-audit.json"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_path.unlink(missing_ok=True)
    except OSError:
        print("Dependency audit failed: output_unavailable", file=sys.stderr)
        return 2
    expected: dict[str, str] = {}
    try:
        contents = requirements.read_bytes()
        summary["requirements_sha256"] = hashlib.sha256(contents).hexdigest()
        expected = _pins(contents.decode("utf-8"))
    except OSError:
        errors.append("requirements_unreadable")
    except ValueError:
        errors.append("requirements_invalid")
    summary["coverage"] = _coverage(expected)
    if not errors:
        command = [
            sys.executable,
            "-m",
            "pip_audit",
            "--no-deps",
            "--disable-pip",
            "--vulnerability-service",
            "pypi",
            "--progress-spinner",
            "off",
            "--format",
            "json",
            "--output",
            str(raw_path),
            "-r",
            str(requirements),
            "--cache-dir",
            str(output_dir / "pip-audit-cache"),
        ]
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                check=False,
            )
            summary["scanner_returncode"] = process.returncode
            if process.returncode not in {0, 1}:
                errors.append("scanner_error")
        except subprocess.TimeoutExpired:
            errors.append("scanner_timeout")
        except OSError:
            errors.append("scanner_unavailable")
        except UnicodeError:
            errors.append("scanner_error")
        try:
            report = cast(object, json.loads(raw_path.read_text(encoding="utf-8")))
            coverage, findings, report_errors = review_report(report, expected)
            summary["coverage"], summary["findings"] = coverage, findings
            errors.extend(report_errors)
        except FileNotFoundError:
            errors.append("report_missing")
        except (OSError, ValueError):
            errors.append("report_invalid")
        if summary["scanner_returncode"] == 1 and not summary["findings"]:
            errors.append("scanner_error")
    if summary["findings"]:
        errors.append("vulnerabilities_found")
    summary["error_codes"] = list(dict.fromkeys(errors))
    if not errors:
        summary["status"] = "passed"
    try:
        (output_dir / "dependency-audit.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        print("Dependency audit failed: summary_write_failed", file=sys.stderr)
        return 2
    for finding in summary["findings"]:
        fixes = ", ".join(finding["fix_versions"]) or "none published"
        print(
            f"{finding['package']}=={finding['version']}: "
            f"{finding['id']}; fixes: {fixes}"
        )
    if not errors:
        print(f"Dependency audit passed: {len(expected)} locked packages checked")
        return 0
    print(
        "Dependency audit failed: " + ", ".join(summary["error_codes"]), file=sys.stderr
    )
    return 1 if summary["error_codes"] == ["vulnerabilities_found"] else 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements", type=Path, default=Path("requirements-production.lock")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("security-reports"))
    args = parser.parse_args(argv)
    return run_audit(args.requirements, args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
