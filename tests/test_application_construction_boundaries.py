from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _python_files(*directories: str):
    for directory in directories:
        base = ROOT / directory
        if not base.exists():
            continue
        yield from base.rglob("*.py")


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_api_does_not_construct_scanner_engines_directly():
    forbidden = ("ScannerEngine(", "EngineOrchestrator(", "IndicatorEngine(")
    offenders = []
    for path in _python_files("api"):
        text = _source(path)
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Direct scanner construction found: {offenders}"


def test_core_does_not_construct_scanner_engines_outside_canonical_factory():
    forbidden = ("ScannerEngine(", "IndicatorEngine(")
    offenders = []
    for path in _python_files("core"):
        if path.name == "application_factory.py":
            continue
        text = _source(path)
        if any(token in text for token in forbidden):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"Direct scanner construction found: {offenders}"


def test_application_factory_is_the_provider_construction_boundary():
    factory = ROOT / "core" / "application_factory.py"
    assert factory.exists(), "Canonical application factory is missing"
    text = _source(factory)
    assert "ProviderFactory" in text
    assert "FullScannerPipeline" in text
    assert "ScannerService" in text
