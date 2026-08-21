from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIRS = ("api", "app", "core", "scanner", "services", "providers", "utils")
LEGACY_NAMES = ("ScannerEngine", "scoring_engine", "engines.scanner_engine")


def _runtime_python_files():
    for dirname in RUNTIME_DIRS:
        base = ROOT / dirname
        if base.exists():
            yield from base.rglob("*.py")


def test_no_direct_legacy_scanner_or_scoring_imports_in_runtime_boundaries():
    offenders = []
    patterns = [
        re.compile(r"from\s+engines\.scanner_engine\s+import"),
        re.compile(r"import\s+engines\.scanner_engine"),
        re.compile(r"from\s+engines\.scoring_engine\s+import"),
        re.compile(r"import\s+engines\.scoring_engine"),
    ]
    for path in _runtime_python_files():
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in patterns):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"Legacy runtime imports detected: {offenders}"


def test_canonical_pipeline_is_the_runtime_scanner_boundary():
    pipeline = ROOT / "scanner" / "full_pipeline.py"
    orchestrator = ROOT / "engines" / "engine_orchestrator.py"
    assert pipeline.exists()
    assert orchestrator.exists()
    assert "EngineOrchestrator" in pipeline.read_text(encoding="utf-8")
    assert "FullScannerPipeline" in pipeline.read_text(encoding="utf-8")


def test_legacy_modules_remain_explicitly_outside_runtime_boundary():
    legacy_engine = ROOT / "engines" / "scanner_engine.py"
    assert legacy_engine.exists()
    # Presence is allowed; runtime imports are what this contract forbids.
    assert "class ScannerEngine" in legacy_engine.read_text(encoding="utf-8")
