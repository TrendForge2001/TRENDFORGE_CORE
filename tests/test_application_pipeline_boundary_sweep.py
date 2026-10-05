from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_BOUNDARY_FILES = [
    ROOT / "api" / "app.py",
    ROOT / "api" / "scanner_service.py",
    ROOT / "core" / "application_factory.py",
    ROOT / "main.py",
    ROOT / "start.py",
]
FORBIDDEN_DIRECT_EXECUTION_MARKERS = (
    "ScannerEngine(",
    "ScoringEngine(",
    "from engines.scanner_engine import",
    "import engines.scanner_engine",
    "from scanner.scoring_engine import",
    "import scanner.scoring_engine",
)


def test_application_boundaries_do_not_bypass_canonical_pipeline():
    offenders: list[str] = []
    for path in CANONICAL_BOUNDARY_FILES:
        text = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_DIRECT_EXECUTION_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, "Direct scanner/scoring execution bypass detected: " + "; ".join(offenders)


def test_application_factory_owns_pipeline_construction():
    text = (ROOT / "core" / "application_factory.py").read_text(encoding="utf-8")
    assert "ProviderFactory" in text
    assert "FullScannerPipeline" in text
    assert "ScannerService" in text


def test_api_delegates_to_scanner_service():
    text = (ROOT / "api" / "app.py").read_text(encoding="utf-8")
    assert "get_scanner_service()" in text
    assert "get_application().scanner_service()" in text
