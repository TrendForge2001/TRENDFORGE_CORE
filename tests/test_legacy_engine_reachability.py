from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CANONICAL_IMPORTS = (
    "CanonicalTechnicalEngine",
    "CanonicalPriceActionEngine",
    "CanonicalMarketRegimeEngine",
    "CanonicalSectorEngine",
    "CanonicalBigSharkEngine",
    "CanonicalCorporateActionEngine",
)
LEGACY_MODULES = (
    "engines.technical_engine",
    "engines.price_action_engine",
    "engines.market_regime_engine",
    "engines.sector_engine",
    "engines.big_shark_engine",
    "engines.corporate_action_engine",
)


def _text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_orchestrator_composes_canonical_engines():
    text = _text("engines/engine_orchestrator.py")
    missing = [name for name in CANONICAL_IMPORTS if name not in text]
    assert not missing, f"Canonical engine composition gaps: {missing}"


def test_scanner_pipeline_does_not_reintroduce_legacy_engine_execution():
    for path in ("scanner/full_pipeline.py", "scanner/pipeline.py"):
        text = _text(path)
        offenders = [module for module in LEGACY_MODULES if module in text]
        assert not offenders, f"Legacy engine imports in {path}: {offenders}"


def test_scanner_engine_is_explicitly_compatibility_only():
    text = _text("scanner/__init__.py")
    assert "FullScannerPipeline" in text
    assert "compatibility facade" in text
