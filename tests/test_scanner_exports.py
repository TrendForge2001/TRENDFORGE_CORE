from __future__ import annotations

import scanner

from scanner.full_pipeline import FullScannerPipeline
from scanner.scanner_engine import ScannerEngine


def test_scanner_exports_canonical_pipeline():
    assert scanner.FullScannerPipeline is FullScannerPipeline


def test_scanner_keeps_only_scanner_compatibility_export():
    assert scanner.ScannerEngine is ScannerEngine
    assert not hasattr(scanner, "ScanResult")


def test_canonical_pipeline_is_package_default_surface():
    assert scanner.__all__ == ["FullScannerPipeline", "ScannerEngine"]
