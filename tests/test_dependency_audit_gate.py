"""Release dependency coverage must be complete before an audit can pass."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import check_dependency_audit as audit


@pytest.fixture
def scanner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    requirements = tmp_path / "requirements-production.lock"
    requirements.write_text("# exact lock\nZope.Interface==8.6\nmy_pkg==1.2.3\n")
    output = tmp_path / "reports"
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.setattr(audit.metadata, "version", lambda _: "2.10.1")

    def install(report: object, returncode: int = 0) -> None:
        def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append((command, kwargs))
            raw = Path(command[command.index("--output") + 1])
            raw.write_text(json.dumps(report))
            return subprocess.CompletedProcess(
                command, returncode, "private stdout", "private stderr"
            )

        monkeypatch.setattr(audit.subprocess, "run", run)

    return requirements, output, calls, install


def complete() -> dict[str, object]:
    return {
        "dependencies": [
            {"name": "zope-interface", "version": "8.6", "vulns": []},
            {"name": "my-pkg", "version": "1.2.3", "vulns": []},
        ],
        "fixes": [],
    }


def reviewed(output: Path) -> dict[str, Any]:
    return json.loads((output / "dependency-audit.json").read_text())


def test_complete_exact_graph_passes_with_bounded_safe_command(scanner, capsys):
    requirements, output, calls, install = scanner
    install(complete())
    assert (
        audit.main(["--requirements", str(requirements), "--output-dir", str(output)])
        == 0
    )
    summary = reviewed(output)
    assert summary["status"] == "passed"
    assert (
        summary["requirements_sha256"]
        == hashlib.sha256(requirements.read_bytes()).hexdigest()
    )
    assert summary["tool_version"] == "2.10.1"
    assert summary["coverage"]["expected_count"] == 2
    assert summary["coverage"]["audited_count"] == 2
    assert summary["findings"] == summary["error_codes"] == []
    command, options = calls[0]
    assert command[:3] == [audit.sys.executable, "-m", "pip_audit"]
    assert "--no-deps" in command and "--disable-pip" in command
    assert command[command.index("--vulnerability-service") + 1] == "pypi"
    assert command[command.index("--progress-spinner") + 1] == "off"
    assert command[command.index("--format") + 1] == "json"
    assert "--strict" not in command
    assert options == {
        "capture_output": True,
        "text": True,
        "timeout": 300,
        "check": False,
    }
    assert (output / "pip-audit.json").is_file()
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err


def test_vulnerabilities_hard_fail_without_echoing_descriptions(scanner, capsys):
    requirements, output, _, install = scanner
    report = complete()
    report["dependencies"][0]["vulns"] = [
        {
            "id": "PYSEC-2026-4320",
            "aliases": ["CVE-2026-12345"],
            "fix_versions": ["9.0"],
            "description": "https://host/?token=never-print-this",
        }
    ]
    install(report, returncode=1)
    assert audit.run_audit(requirements, output) == 1
    summary = reviewed(output)
    assert summary["status"] == "failed"
    assert summary["error_codes"] == ["vulnerabilities_found"]
    assert summary["coverage"]["audited_count"] == 2
    assert summary["findings"][0]["aliases"] == ["CVE-2026-12345"]
    assert "description" not in json.dumps(summary)
    captured = capsys.readouterr()
    assert "zope-interface==8.6: PYSEC-2026-4320; fixes: 9.0" in captured.out
    assert "never-print-this" not in captured.out + captured.err


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ("missing", "coverage_missing"),
        ("extra", "coverage_unexpected"),
        ("duplicate", "coverage_duplicate"),
        ("mismatch", "coverage_version_mismatch"),
        ("skipped", "coverage_skipped"),
        ("missing_vulns", "report_malformed_dependency"),
        ("bad_vulns", "report_malformed_dependency"),
        ("bad_advisory", "report_malformed_dependency"),
        ("bad_fix", "report_malformed_dependency"),
    ],
)
def test_coverage_and_malformed_entries_fail_closed(scanner, capsys, change, error):
    requirements, output, _, install = scanner
    report = complete()
    dependencies = report["dependencies"]
    if change == "missing":
        dependencies.pop()
    elif change == "extra":
        dependencies.append({"name": "extra", "version": "1.0", "vulns": []})
    elif change == "duplicate":
        dependencies.append({"name": "MY_pkg", "version": "1.2.3", "vulns": []})
    elif change == "mismatch":
        dependencies[0]["version"] = "9.0"
    elif change == "skipped":
        dependencies[0]["skip_reason"] = (
            "private upstream response token=never-print-this"
        )
    elif change == "missing_vulns":
        del dependencies[0]["vulns"]
    elif change == "bad_vulns":
        dependencies[0]["vulns"] = {"id": "CVE-2026-12345"}
    else:
        dependencies[0]["vulns"] = [
            {
                "id": "token=never-print-this"
                if change == "bad_advisory"
                else "CVE-2026-12345",
                "fix_versions": ["token=never-print-this"]
                if change == "bad_fix"
                else [],
            }
        ]
    install(report)
    assert audit.run_audit(requirements, output) == 2
    summary = reviewed(output)
    assert summary["status"] == "failed"
    assert error in summary["error_codes"]
    assert "never-print-this" not in json.dumps(summary)
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err


@pytest.mark.parametrize(
    "report", [None, [], {}, {"dependencies": {}}, {"dependencies": [None]}]
)
def test_malformed_reports_never_pass(scanner, report):
    requirements, output, _, install = scanner
    install(report)
    assert audit.run_audit(requirements, output) == 2
    assert reviewed(output)["error_codes"]


def test_scanner_failure_is_not_masked_by_complete_report(scanner, capsys):
    requirements, output, _, install = scanner
    install(complete(), returncode=2)
    assert audit.run_audit(requirements, output) == 2
    assert reviewed(output)["error_codes"] == ["scanner_error"]
    captured = capsys.readouterr()
    assert "private" not in captured.out + captured.err


def test_nonzero_without_findings_is_scanner_error(scanner):
    requirements, output, _, install = scanner
    install(complete(), returncode=1)
    assert audit.run_audit(requirements, output) == 2
    assert reviewed(output)["error_codes"] == ["scanner_error"]


def test_stale_raw_report_is_deleted_and_missing_report_fails(scanner, monkeypatch):
    requirements, output, _, _ = scanner
    output.mkdir()
    (output / "pip-audit.json").write_text(json.dumps(complete()))

    def run(command, **_):
        assert not (output / "pip-audit.json").exists()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.run_audit(requirements, output) == 2
    assert reviewed(output)["error_codes"] == ["report_missing"]


def test_timeout_writes_failure_artifact_without_echoing_subprocess_output(
    scanner, monkeypatch, capsys
):
    requirements, output, _, _ = scanner

    def run(command, **options):
        assert options["timeout"] == 300
        raise subprocess.TimeoutExpired(
            command, 300, output="token=never-print-this", stderr="private"
        )

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.run_audit(requirements, output) == 2
    summary = reviewed(output)
    assert "scanner_timeout" in summary["error_codes"]
    assert summary["requirements_sha256"]
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err
    assert "private" not in captured.out + captured.err


@pytest.mark.parametrize(
    "contents",
    ["", "one>=1.0\n", "one==1.0\nONE==1.0\n", "https://host/?token=private"],
)
def test_invalid_lock_fails_without_launching_scanner(scanner, contents):
    requirements, output, calls, install = scanner
    requirements.write_text(contents)
    install(complete())
    assert audit.run_audit(requirements, output) == 2
    assert calls == []
    assert reviewed(output)["error_codes"] == ["requirements_invalid"]


def test_unavailable_scanner_is_sanitized(scanner, monkeypatch, capsys):
    requirements, output, _, _ = scanner

    def run(*_, **__):
        raise OSError("https://host/?token=never-print-this")

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.run_audit(requirements, output) == 2
    assert "scanner_unavailable" in reviewed(output)["error_codes"]
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err


def test_missing_requirements_writes_summary_without_scanning(scanner):
    requirements, output, calls, install = scanner
    requirements.unlink()
    install(complete())
    assert audit.run_audit(requirements, output) == 2
    assert calls == []
    summary = reviewed(output)
    assert summary["requirements_sha256"] is None
    assert summary["error_codes"] == ["requirements_unreadable"]


def test_invalid_json_is_sanitized_and_retained_as_raw_artifact(
    scanner, monkeypatch, capsys
):
    requirements, output, _, _ = scanner

    def run(command, **_):
        Path(command[command.index("--output") + 1]).write_text(
            "not JSON: token=never-print-this"
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.run_audit(requirements, output) == 2
    assert reviewed(output)["error_codes"] == ["report_invalid"]
    assert (output / "pip-audit.json").read_text().startswith("not JSON")
    captured = capsys.readouterr()
    assert "never-print-this" not in captured.out + captured.err


def test_skipped_package_without_version_is_not_counted_as_audited(scanner):
    requirements, output, _, install = scanner
    report = complete()
    report["dependencies"][0] = {
        "name": "zope-interface",
        "skip_reason": "not found upstream",
    }
    install(report)
    assert audit.run_audit(requirements, output) == 2
    summary = reviewed(output)
    assert summary["coverage"]["skipped"] == ["zope-interface"]
    assert summary["coverage"]["audited_count"] == 1
    assert "coverage_skipped" in summary["error_codes"]


def test_unfixed_advisory_still_hard_fails(scanner, capsys):
    requirements, output, _, install = scanner
    report = complete()
    report["dependencies"][0]["vulns"] = [{"id": "CVE-2026-12345", "fix_versions": []}]
    install(report, returncode=1)
    assert audit.run_audit(requirements, output) == 1
    assert reviewed(output)["findings"][0]["fix_versions"] == []
    assert "fixes: none published" in capsys.readouterr().out
