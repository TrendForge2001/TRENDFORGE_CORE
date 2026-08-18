from __future__ import annotations

from engines.scanner_engine import ScannerEngine as CompatibilityScannerEngine
from scanner.scanner_engine import ScannerEngine as CanonicalScannerEngine


def test_engines_scanner_engine_is_canonical_subclass():
    assert issubclass(CompatibilityScannerEngine, CanonicalScannerEngine)
    assert CompatibilityScannerEngine.__mro__[1] is CanonicalScannerEngine


def test_compatibility_scanner_engine_does_not_override_execution_methods():
    assert "scan" not in CompatibilityScannerEngine.__dict__
    assert "scan_payload" not in CompatibilityScannerEngine.__dict__
    assert "scan_many" not in CompatibilityScannerEngine.__dict__
    assert "scan_payload_many" not in CompatibilityScannerEngine.__dict__
    assert "rank" not in CompatibilityScannerEngine.__dict__


def test_compatibility_scanner_engine_exports_only_alias():
    assert CompatibilityScannerEngine.__module__ == "engines.scanner_engine"
    assert CompatibilityScannerEngine.__name__ == "ScannerEngine"
