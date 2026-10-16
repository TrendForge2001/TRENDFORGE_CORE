from __future__ import annotations

from database.database import Database
from database.migrations import institutional_sector_snapshots
from database.repositories.institutional_sector_repository import (
    InstitutionalSectorRepository,
)


def test_repository_upserts_institutional_snapshot(tmp_path):
    db = Database(str(tmp_path / "snapshots.db"))
    try:
        institutional_sector_snapshots.migrate(db)
        repo = InstitutionalSectorRepository(db=db)

        repo.save(
            "institutional",
            "TCS",
            {"score": 60},
            universe="NSE/BSE",
            sample_size=1,
        )
        repo.save(
            "institutional",
            "TCS",
            {"score": 72},
            universe="NSE/BSE",
            sample_size=1,
        )

        assert repo.count(kind="institutional") == 1
        row = repo.get("institutional", "TCS")
        assert row is not None
        assert row["payload"]["score"] == 72
    finally:
        db.close()


def test_repository_keeps_sector_and_institutional_kinds_separate(
    tmp_path,
):
    db = Database(str(tmp_path / "snapshots.db"))
    try:
        institutional_sector_snapshots.migrate(db)
        repo = InstitutionalSectorRepository(db=db)

        repo.save(
            "institutional",
            "NIFTY 500",
            {"score": 40},
        )
        repo.save(
            "sector_strength",
            "NIFTY 500",
            {"sector_count": 5},
        )

        assert repo.count(kind="institutional") == 1
        assert repo.count(kind="sector_strength") == 1
        assert (
            repo.get(
                "sector_strength",
                "NIFTY 500",
            )["payload"]["sector_count"]
            == 5
        )
    finally:
        db.close()
