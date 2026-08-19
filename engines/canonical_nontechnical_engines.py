"""Payload-only canonical wrappers for non-technical scanner engines."""
from __future__ import annotations

from engines.big_shark_engine import BigSharkEngine
from engines.sector_engine import SectorEngine
from engines.corporate_action_engine import CorporateActionEngine
from engines.canonical_data_execution import PAYLOAD_ONLY


class CanonicalBigSharkEngine(BigSharkEngine):
    """Big Shark scorer with external acquisition disabled."""
    def __init__(self):
        super().__init__(provider=PAYLOAD_ONLY, repository=PAYLOAD_ONLY)


class CanonicalSectorEngine(SectorEngine):
    """Sector scorer with external acquisition disabled."""
    def __init__(self):
        super().__init__(provider=PAYLOAD_ONLY, repository=PAYLOAD_ONLY)


class CanonicalCorporateActionEngine(CorporateActionEngine):
    """Corporate-action scorer with external acquisition disabled."""
    def __init__(self):
        super().__init__(provider=PAYLOAD_ONLY, repository=PAYLOAD_ONLY)


__all__ = [
    "CanonicalBigSharkEngine",
    "CanonicalSectorEngine",
    "CanonicalCorporateActionEngine",
]
