"""Real Git/detector regressions for the offline release secret gate."""

from __future__ import annotations

import hashlib
import json
import secrets
import subprocess

import pytest
import requests

from scripts import check_secrets


def git(root, *args):
    return (
        subprocess.check_output(
            [
                "git",
                "-C",
                str(root),
                "-c",
                "user.name=Security test",
                "-c",
                "user.email=security-test@example.invalid",
                *args,
            ],
            stderr=subprocess.DEVNULL,
        )
        .decode()
        .strip()
    )


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init")
    (tmp_path / "README.md").write_text("A clean repository.\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "Initial source")
    return tmp_path


def write_token(root, *, filename="credentials.py", pragma=False):
    # Construct synthetic tokens at runtime so the tests contain no embedded
    # credential-looking constant or static scanner exception.
    token = "ghp_" + secrets.token_hex(18)
    suffix = "  # pragma: allowlist secret" if pragma else ""
    (root / filename).write_text(f"GITHUB_TOKEN = '{token}'{suffix}\n")
    return token


def assert_redacted(report, *tokens):
    serialized = json.dumps(report)
    for token in tokens:
        assert token not in serialized


def test_clean_repository_scans_complete_history_and_current_source(repository):
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "pass"
    assert report["errors"] == []
    assert report["coverage"] == {
        "current_files": 1,
        "history_versions": 1,
        "history_blobs": 1,
    }


@pytest.mark.parametrize(
    "filename",
    [
        "credentials.py",
        "package-lock.json",
        "swagger-ui.html",
        "odd\nname.py",
    ],
)
def test_untracked_secret_and_inline_pragma_cannot_bypass_gate(repository, filename):
    token = write_token(repository, filename=filename, pragma=True)
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "findings"
    assert report["current"]
    assert report["history"] == []
    assert all(not item["reviewed"] for item in report["current"])
    assert_redacted(report, token)


def test_known_token_inside_function_call_is_not_filtered_as_an_indirect_reference(
    repository,
):
    token = "ghp_" + secrets.token_hex(18)
    (repository / "client.py").write_text(f"client = connect(token='{token}')\n")
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "findings"
    assert any(item["type"] == "GitHub Token" for item in report["current"])
    assert_redacted(report, token)


def test_deleted_history_secrets_still_fail_with_safe_blob_location(repository):
    token = write_token(repository)
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Add temporary fixture")
    git(repository, "rm", "credentials.py")
    git(repository, "commit", "-m", "Remove temporary fixture")
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "findings"
    assert report["current"] == []
    assert report["history"]
    for finding in report["history"]:
        assert finding["path"] == "credentials.py"
        assert len(finding["example_commit"]) == len(finding["example_blob"]) == 40
        assert finding["versions"] == 1
    assert_redacted(report, token)


def test_merge_only_blob_is_included_in_history(repository):
    initial = git(repository, "rev-parse", "HEAD")
    clean_tree = git(repository, "rev-parse", "HEAD^{tree}")
    first_parent = git(repository, "commit-tree", clean_tree, "-p", initial, "-m", "A")
    second_parent = git(repository, "commit-tree", clean_tree, "-p", initial, "-m", "B")
    token = write_token(repository)
    git(repository, "add", ".")
    merge_tree = git(repository, "write-tree")
    merge = git(
        repository,
        "commit-tree",
        merge_tree,
        "-p",
        first_parent,
        "-p",
        second_parent,
        "-m",
        "Merge fixture",
    )
    git(repository, "update-ref", "HEAD", merge)
    git(repository, "rm", "credentials.py")
    git(repository, "commit", "-m", "Remove merged fixture")
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "findings"
    assert report["current"] == []
    assert report["history"]
    assert {item["example_commit"] for item in report["history"]} == {merge}
    assert_redacted(report, token)


def test_exact_review_requires_source_path_detector_and_value_match(repository):
    first_token = write_token(repository)
    git(repository, "add", ".")
    git(repository, "commit", "-m", "Synthetic fixture")
    initial = check_secrets.scan_repository(repository)
    manifest = {"version": 1}
    for source in ("current", "history"):
        manifest[source] = [
            {key: item[key] for key in ("path", "type", "fingerprint")}
            | {"reason": "Synthetic scanner regression fixture"}
            for item in initial[source]
        ]
    review_file = repository / "reviews.json"
    review_file.write_text(json.dumps(manifest))
    reviewed = check_secrets.scan_repository(repository, review_file)
    assert reviewed["status"] == "pass"
    second_token = write_token(repository)
    changed = check_secrets.scan_repository(repository, review_file)
    assert changed["status"] == "findings"
    assert all(not item["reviewed"] for item in changed["current"])
    assert all(item["reviewed"] for item in changed["history"])
    assert_redacted(changed, first_token, second_token)


def test_binary_input_fails_closed_instead_of_a_clean_scan(repository):
    (repository / "unsupported.bin").write_bytes(b"unsupported\0binary")
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "error"
    assert report["errors"] == ["binary_content_not_supported"]
    assert report["failed_path"] == "unsupported.bin"


def test_shallow_history_fails_closed(repository, tmp_path):
    clone = tmp_path / "shallow"
    git(repository, "clone", "--depth=1", repository.as_uri(), str(clone))
    report = check_secrets.scan_repository(clone)
    assert report["status"] == "error"
    assert report["errors"] == ["complete_history_required"]


def test_report_and_stdout_do_not_expose_matched_values(
    repository, tmp_path, monkeypatch, capsys
):
    token = write_token(repository)
    output = tmp_path / "reports"
    monkeypatch.setattr(
        "sys.argv",
        ["check_secrets", "--root", str(repository), "--output-dir", str(output)],
    )
    assert check_secrets.main() == 1
    report_text = (output / "secret-scan.json").read_text()
    captured = capsys.readouterr()
    assert token not in report_text + captured.out + captured.err
    fingerprint = (
        "sha256:"
        + hashlib.sha256((repository / "credentials.py").read_bytes()).hexdigest()
    )
    assert fingerprint in report_text


def test_scanner_failure_is_safe_and_cannot_be_reported_as_pass(
    repository, monkeypatch
):
    token = "diagnostic-" + secrets.token_hex(12)

    def broken(*args, **kwargs):
        raise RuntimeError(token)

    monkeypatch.setattr(check_secrets, "_scan_content", broken)
    report = check_secrets.scan_repository(repository)
    assert report["status"] == "error"
    assert report["errors"] == ["secret_scan_failed"]
    assert_redacted(report, token)


@pytest.fixture(autouse=True)
def forbid_token_verification_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Secret scanning must remain offline")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
