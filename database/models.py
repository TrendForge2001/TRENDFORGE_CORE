"""Compatibility exports for TrendForge database models.

The canonical ORM base lives in :mod:`database.base`; concrete models live
under :mod:`database.models` submodules in the original project layout.
"""

try:
    from database.base import Base
except ImportError:  # pragma: no cover - allows partial environments to import this module
    Base = None

__all__ = ["Base"]
