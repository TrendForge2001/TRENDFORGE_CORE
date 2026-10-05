from __future__ import annotations

from engines.big_shark_engine import BigSharkEngine


class ExplodingProvider:
    def __getattr__(self, name):
        if name.startswith("get_") or name.startswith("fetch_"):
            raise AssertionError("BigSharkEngine must not acquire external data during evaluate()")
        raise AttributeError(name)


def test_big_shark_engine_uses_payload_without_provider_fetch():
    engine = BigSharkEngine(provider=ExplodingProvider())
    result = engine.evaluate({
        "symbol": "ABC",
        "shareholding": {"fii": 12.0, "dii": 8.0, "promoter": 55.0},
        "holding_changes": [],
        "deals": [],
    })
    assert result.engine == "Big Shark Engine"
    assert result.metrics["data_quality"] is True


def test_big_shark_engine_missing_payload_does_not_invent_activity():
    engine = BigSharkEngine(provider=None, repository=None)
    result = engine.evaluate({"symbol": "ABC"})
    assert result.metrics["data_quality"] is False
    assert result.score == 0
    assert any("unavailable" in warning.lower() for warning in result.warnings)


def test_big_shark_engine_payload_takes_precedence_over_provider():
    class Provider:
        def get_shareholding(self, symbol):
            return {"shareholding": {"fii": 99.0}}

    engine = BigSharkEngine(provider=Provider())
    result = engine.evaluate({
        "symbol": "ABC",
        "shareholding": {"fii": 10.0, "dii": 5.0, "promoter": 50.0},
    })
    assert result.metrics["ownership"]["fii"] == 10.0
