from __future__ import annotations

from engines.big_shark_engine import BigSharkEngine
from engines.sector_engine import SectorEngine
from engines.corporate_action_engine import CorporateActionEngine


class ExplodingProvider:
    def __getattr__(self, name):
        def call(*args, **kwargs):
            raise AssertionError(f"external fetch invoked: {name}")
        return call


def test_big_shark_payload_is_sufficient_without_external_fetch():
    payload = {
        "symbol": "ABC",
        "shareholding": {"promoter": 50, "fii": 20, "dii": 15},
        "holding_changes": [{"category": "FII", "change": 2}],
        "deals": [{"side": "BUY", "value": 30}],
    }
    result = BigSharkEngine(provider=ExplodingProvider()).evaluate(payload)
    assert result.metrics["symbol"] == "ABC"


def test_sector_payload_is_used_without_external_fetch():
    payload = {
        "symbol": "ABC",
        "sector_name": "BANKING",
        "sector_snapshot": {
            "sector": "BANKING",
            "change_1d": 1.2,
            "change_1w": 2.5,
            "change_1m": 4.0,
            "relative_strength": 70,
            "volume_ratio": 1.2,
            "advancing": 8,
            "declining": 2,
            "leadership_score": 70,
        },
    }
    result = SectorEngine(provider=ExplodingProvider()).evaluate(payload)
    assert result.metrics["sector"] == "BANKING"


def test_corporate_actions_payload_is_used_without_external_fetch():
    payload = {
        "symbol": "ABC",
        "corporate_actions": [
            {"type": "buyback", "title": "Board approves buyback", "date": "2030-01-10"}
        ],
    }
    result = CorporateActionEngine(provider=ExplodingProvider()).evaluate(payload)
    assert result.metrics["event_count"] == 1
