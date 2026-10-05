from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _requirements() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {line.split("=")[0].split(">")[0].split("<")[0].split("[")[0] for line in lines if line.strip() and not line.startswith("#")}


def test_core_runtime_dependencies_are_pinned_to_major_compatible_ranges():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    for dependency in (
        "pandas>=2.1,<3",
        "numpy>=1.24,<3",
        "requests>=2.31,<3",
        "fastapi>=0.115,<1",
        "uvicorn[standard]>=0.34,<1",
    ):
        assert dependency in text


def test_previous_pandas_ta_dependency_conflict_is_not_reintroduced():
    text = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "pandas-ta" not in text
    assert "pandas_ta" not in text


def test_database_and_external_provider_dependencies_are_declared():
    requirements = _requirements()
    assert {"SQLAlchemy", "yfinance", "kiteconnect", "python-dotenv"}.issubset(requirements)


def test_excel_export_dependency_is_declared():
    assert "openpyxl" in _requirements()
