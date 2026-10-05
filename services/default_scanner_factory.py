"""Default runnable scanner construction for TrendForge MVP."""
from __future__ import annotations

from core.application_factory import build_application_factory

def build_default_scanner(max_workers: int = 8):
    """Build the scanner through the canonical application composition root."""
    # max_workers is retained for legacy callers; canonical construction owns tuning.
    return build_application_factory().scanner_service()

__all__ = ["build_default_scanner"]
