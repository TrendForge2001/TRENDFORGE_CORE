from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOUNDARY_DIRS = ("api", "scanner", "pipeline", "services", "engines")
FORBIDDEN = (
    "ApplicationFactory()",
    "ProviderFactory()",
    "FullScannerPipeline()",
    "EngineOrchestrator()",
    "ScannerEngine()",
    "ScoringEngine()",
)
EXCLUDED = {"core/application_factory.py", "core/domain_provider_factory.py"}


def test_non_core_runtime_does_not_create_composition_root_objects():
    offenders: list[str] = []
    for dirname in BOUNDARY_DIRS:
        for path in (ROOT / dirname).rglob("*.py"):
            rel = str(path.relative_to(ROOT)).replace("\\", "/")
            if rel in EXCLUDED:
                continue
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN:
                if marker in text:
                    offenders.append(f"{rel}: {marker}")
    assert not offenders, "Composition-root bypasses detected: " + "; ".join(offenders)


def test_start_and_main_remain_thin_entrypoints():
    for name in ("start.py", "main.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "ApplicationFactory" in text or name == "start.py"
