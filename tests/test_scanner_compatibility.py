from __future__ import annotations

from engines.scanner_engine import ScannerEngine as LegacyScannerEngine
from scanner.scanner_engine import ScannerEngine as CanonicalScannerEngine


def test_legacy_scanner_engine_is_only_a_compatibility_alias():
    assert issubclass(LegacyScannerEngine, CanonicalScannerEngine)
    assert LegacyScannerEngine.__mro__[1] is CanonicalScannerEngine


def test_legacy_scanner_engine_does_not_define_independent_scan_logic():
    assert LegacyScannerEngine.scan is CanonicalScannerEngine.scan
    assert LegacyScannerEngine.scan_payload is CanonicalScannerEngine.scan_payload
    assert LegacyScannerEngine.scan_many is CanonicalScannerEngine.scan_many
    assert LegacyScannerEngine.scan_payload_many is CanonicalScannerEngine.scan_payload_many


def test_canonical_scanner_engine_is_the_single_scanner_implementation():
    assert CanonicalScannerEngine.__module__ == "scanner.scanner_engine"
