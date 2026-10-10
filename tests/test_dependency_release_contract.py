from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
PRODUCTION_LOCK = ROOT / "requirements-production.lock"
RENDER = ROOT / "render.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"


def _requirements() -> dict[str, str]:
    entries = {}
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("=", 1)[0].split(">", 1)[0].split("<", 1)[0].strip().lower()
        entries[name] = line
    return entries


def test_runtime_dependencies_are_declared():
    deps = _requirements()
    for name in ("pandas", "numpy", "requests", "python-dotenv", "cachetools", "yfinance", "kiteconnect", "sqlalchemy", "openpyxl"):
        assert name in deps, f"Missing runtime dependency: {name}"


def test_requirements_do_not_reintroduce_removed_pandas_ta_dependency():
    deps = _requirements()
    assert "pandas-ta" not in deps


def test_numpy_and_pandas_ranges_are_open_ended_at_current_major_limit():
    deps = _requirements()
    assert "<3" in deps["numpy"]
    assert "<3" in deps["pandas"]


def test_ci_uses_supported_python_versions_and_requirements_file():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '"3.11"' in workflow
    assert '"3.12"' in workflow
    assert "pip install -r requirements.txt pytest" in workflow
    assert "python -m pytest -q" in workflow


def _locked_requirements() -> dict[str, str]:
    entries = {}
    for raw in PRODUCTION_LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "==" in line
        name, version = line.split("==", 1)
        entries[name.strip().lower().replace("_", "-")] = version.strip()
    return entries


def test_production_lock_contains_only_exact_versions():
    entries = _locked_requirements()
    assert len(entries) >= 50
    assert "pytest" not in entries
    for version in entries.values():
        assert version
        assert not any(token in version for token in (">", "<", "~", "*"))


def test_every_direct_runtime_dependency_is_present_in_production_lock():
    direct = {
        name.replace("_", "-")
        for name in _requirements()
    }
    locked = set(_locked_requirements())
    assert direct <= locked


def test_render_installs_production_lock_not_open_ranges():
    render = RENDER.read_text(encoding="utf-8")
    assert "python -m pip install -r requirements-production.lock" in render
    assert "pip install -r requirements.txt" not in render


def test_ci_validates_broad_ranges_and_locked_production_graph():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pip install -r requirements.txt pytest" in workflow
    assert "pip install -r requirements-production.lock" in workflow
    assert "PRODUCTION_LOCK_MATCH=true" in workflow
    assert "production-dependency-audit:" in workflow
