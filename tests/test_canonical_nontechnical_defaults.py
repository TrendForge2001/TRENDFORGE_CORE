from __future__ import annotations

from engines.canonical_nontechnical_engines import CanonicalBigSharkEngine, CanonicalSectorEngine
from engines.contracted_big_shark_engine import ContractedBigSharkEngine
from engines.contracted_sector_engine import ContractedSectorEngine


def test_contracted_sector_defaults_to_canonical_engine():
    assert isinstance(ContractedSectorEngine().engine, CanonicalSectorEngine)


def test_contracted_big_shark_defaults_to_canonical_engine():
    assert isinstance(ContractedBigSharkEngine().engine, CanonicalBigSharkEngine)
