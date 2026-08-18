"""Compatibility contract for TrendForge fundamental providers.

The canonical FundamentalData contract lives in api.fundamentals.  This module
keeps provider implementations under ``providers`` import-compatible while
avoiding a second data model.
"""

from api.fundamentals import FundamentalData, FundamentalProvider

__all__ = ["FundamentalData", "FundamentalProvider"]
