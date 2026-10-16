from __future__ import annotations

from database.database import Database
from database.migrations import intelligence_events
from database.repositories.intelligence_event_repository import (
    IntelligenceEventRepository,
)


def test_intelligence_repository_upserts_and_deduplicates(tmp_path):
    db = Database(str(tmp_path / "intel.db"))
    try:
        intelligence_events.migrate(db)
        repo = IntelligenceEventRepository(db=db)

        base = {
            "event_key": "abc",
            "domain": "news",
            "symbol": "TCS",
            "event_type": "NEWS",
            "headline": "TCS wins order",
            "impact_score": 2,
            "details": {"methodology": "keyword_heuristic_v1"},
        }
        repo.upsert(base)
        repo.upsert({**base, "impact_score": 4})

        assert repo.count() == 1
        row = repo.by_key("abc")
        assert row is not None
        assert row["impact_score"] == 4
        assert row["details"]["methodology"] == "keyword_heuristic_v1"
    finally:
        db.close()


def test_intelligence_repository_filters_domain_and_symbol(tmp_path):
    db = Database(str(tmp_path / "intel.db"))
    try:
        intelligence_events.migrate(db)
        repo = IntelligenceEventRepository(db=db)
        repo.upsert(
            {
                "event_key": "n1",
                "domain": "news",
                "symbol": "TCS",
                "headline": "one",
            }
        )
        repo.upsert(
            {
                "event_key": "c1",
                "domain": "corporate_action",
                "symbol": "INFY",
                "headline": "two",
            }
        )

        assert len(repo.list(domain="news")) == 1
        assert len(repo.list(symbol="INFY")) == 1
        assert repo.count(domain="corporate_action") == 1
    finally:
        db.close()
