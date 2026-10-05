from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
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
