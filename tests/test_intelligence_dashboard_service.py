from __future__ import annotations

from datetime import datetime, timedelta, timezone

from services.intelligence_dashboard_service import (
    IntelligenceDashboardService,
)


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def upsert(self, event):
        self.rows[event["event_key"]] = dict(event)
        return dict(event)

    def list(self, *, domain=None, symbol=None, limit=100):
        rows = list(self.rows.values())
        if domain:
            rows = [
                row for row in rows
                if row.get("domain") == domain
            ]
        if symbol:
            rows = [
                row for row in rows
                if row.get("symbol") == symbol
            ]
        return rows[:limit]

    def count(self, *, domain=None, symbol=None):
        return len(
            self.list(
                domain=domain,
                symbol=symbol,
                limit=500,
            )
        )

    def latest_fetch_at(self, *, domain, symbol):
        return "2026-10-16T03:30:00+00:00"

    def close(self):
        pass


class FakeNews:
    BREAKING_KEYWORDS = {"order", "results"}

    def __init__(self):
        self.provider = type("FakeNewsProvider", (), {})()

    def get_news(self, symbol, force_refresh=False):
        return [
            {
                "title": f"{symbol} wins major order",
                "publisher": "Wire",
                "link": "https://example.test/news",
                "published": 1792121400,
                "source": "Fake",
                "sentiment": "Positive",
                "score": 4,
            }
        ]


class FakeCorporate:
    EVENT_SCORES = {
        "BONUS": 8,
        "DIVIDEND": 5,
        "PENALTY": -6,
    }

    def __init__(self):
        self.provider = type("FakeCorporateProvider", (), {})()

    def get_actions(
        self,
        symbol,
        force_refresh=False,
        days=120,
    ):
        future = (
            datetime.now(timezone.utc)
            + timedelta(days=10)
        ).date().isoformat()
        return [
            {
                "symbol": symbol,
                "subject": "Bonus issue",
                "purpose": "BONUS",
                "date": future,
                "score": 8,
                "details": {
                    "source": "NSE",
                },
            }
        ]


def build_service():
    return IntelligenceDashboardService(
        news_service=FakeNews(),
        corporate_action_service=FakeCorporate(),
        repository=FakeRepository(),
    )


def test_refresh_normalizes_and_persists_both_domains():
    service = build_service()

    result = service.refresh(
        symbols=["tcs", "TCS"],
        domains=["news", "corporate_actions"],
        days=90,
    )

    assert result["symbols"] == ["TCS"]
    assert result["news_events"] == 1
    assert result["corporate_action_events"] == 1
    assert result["persisted_events"] == 2

    news = service.news("TCS")
    assert news["breaking"] == 1
    assert news["positive"] == 1
    assert news["average_impact_score"] == 4.0

    actions = service.corporate_actions("TCS")
    assert actions["high_impact"] == 1
    assert actions["upcoming"] == 1
    assert actions["next_event_at"]


def test_refresh_is_idempotent_for_same_source_evidence():
    service = build_service()

    service.refresh(symbols=["TCS"])
    service.refresh(symbols=["TCS"])

    assert service.repository.count() == 2


def test_summary_uses_available_evidence_without_zero_dilution():
    service = build_service()
    service.refresh(
        symbols=["TCS"],
        domains=["news"],
    )

    summary = service.summary("TCS")

    assert summary["combined_intelligence_score"] == 4.0
    assert summary["score_range"] == [-10, 10]
    assert summary["interpretation"] == (
        "heuristic_evidence_summary_not_trade_signal"
    )


def test_readiness_labels_heuristics_not_ai():
    result = build_service().readiness()

    assert result["news_scoring"] == "keyword_heuristic_v1"
    assert (
        result["corporate_action_scoring"]
        == "event_weight_heuristic_v1"
    )
    assert result["ai_sentiment"] is False
