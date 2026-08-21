from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FILES = [
    ROOT / "engines" / "engine_orchestrator.py",
    ROOT / "scanner" / "full_pipeline.py",
]
LEGACY_NAMES = (
    "from engines.scanner_engine import",
    "import engines.scanner_engine",
    "from scanner.scanner_engine import",
    "import scanner.scanner_engine",
)


def test_canonical_runtime_files_do_not_import_legacy_scanner_engine():
    offenders = []
    for path in CANONICAL_FILES:
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in LEGACY_NAMES):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"Canonical runtime imports legacy ScannerEngine: {offenders}"


def test_scanner_engine_is_explicitly_compatibility_only():
    path = ROOT / "scanner" / "scanner_engine.py"
    text = path.read_text(encoding="utf-8")
    assert "Legacy scanner compatibility facade" in text
    assert "FullScannerPipeline" in text
    assert "all actual execution is delegated" in text
