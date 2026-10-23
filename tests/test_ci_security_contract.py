"""Keep release verification dependent on actual security scan evidence."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_render_verification_requires_both_security_jobs():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    jobs = workflow["jobs"]
    assert {"dependency-vulnerabilities", "secret-scan"} <= set(
        jobs["render-deployment"]["needs"]
    )
    for name in ("dependency-vulnerabilities", "secret-scan"):
        job = jobs[name]
        assert "if" not in job
        scan = next(
            step for step in job["steps"] if "scripts.check_" in step.get("run", "")
        )
        assert "continue-on-error" not in scan
        upload = next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/upload-artifact@")
        )
        assert upload["if"] == "always()"
        assert upload["with"]["if-no-files-found"] == "error"
        summary = (
            "dependency-audit.json"
            if name == "dependency-vulnerabilities"
            else "secret-scan.json"
        )
        assert upload["with"]["path"] == f"security-reports/{summary}"


def test_secret_scan_has_complete_history_and_no_persisted_checkout_credentials():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    steps = workflow["jobs"]["secret-scan"]["steps"]
    checkout = next(
        step for step in steps if step.get("uses", "").startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is False


def test_test_tooling_cannot_upgrade_the_production_lock():
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    steps = workflow["jobs"]["production-dependency-audit"]["steps"]
    test_run = next(
        step["run"]
        for step in steps
        if "pytest-production-results.xml" in step.get("run", "")
    )
    assert "-c requirements-production.lock -r requirements-test.txt" in test_run
    runtime_names = {
        line.split("==")[0].lower()
        for line in (ROOT / "requirements-production.lock").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert not {"pytest", "httpx2", "pip-audit", "detect-secrets"} & runtime_names
