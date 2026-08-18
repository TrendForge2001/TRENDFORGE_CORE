"""Legacy scanner compatibility shim.

The canonical scanner lives in ``scanner.scanner_engine`` and routes all
analysis through ``EngineOrchestrator``.  This module remains importable for
older callers but deliberately does not execute the legacy engine chain.
"""
from __future__ import annotations

from typing import Any

from scanner.scanner_engine import ScannerEngine as CanonicalScannerEngine


class ScannerEngine(CanonicalScannerEngine):
    """Backward-compatible alias for the canonical ScannerEngine."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)


__all__ = ["ScannerEngine"]
