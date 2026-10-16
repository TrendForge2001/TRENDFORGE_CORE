from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.market_context_service import MarketContextService


@dataclass
class Member:
    symbol: str
    sector: str


class FakeUniverse:
    def __init__(self, count=40):
        self.members = [
            Member(
                symbol=f"S{i:03d}",
                sector="IT" if i % 2 == 0 else "BANK",
            )
            for i in range(count)
        ]

    def ensure_loaded(self, refresh=False):
        return list(self.members)


class FakeRepository:
    def __init__(self):
        self.records = {}

    def save(self, kind, payload, *, universe, sample_size):
        self.records[kind] = {
            "kind": kind,
            "universe": universe,
            "sample_size": sample_size,
            "created_at": "2026-10-16T10:00:00+00:00",
            "payload": dict(payload),
        }
        return dict(self.records[kind])

    def get(self, kind):
        record = self.records.get(kind)
        return dict(record) if record else None

    def close(self):
        pass


class FakeMarketData:
    def __init__(self):
        self.requested = []

    @staticmethod
    def _frame(index):
        dates = pd.date_range(
            "2025-12-01",
            periods=230,
            freq="D",
        )
        base = pd.Series(
            [100.0 + step * 0.4 for step in range(230)],
            index=dates,
        )
        shift = index * 0.01
        close = base + shift
        return pd.DataFrame(
            {
                "open": close - 0.2,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": [
                    1_000_000 + step * 100 + index
                    for step in range(230)
                ],
            },
            index=dates,
        )

    def begin_observation(self):
        pass

    def batch_candles_with_errors(
        self,
        symbols,
        period="1y",
        interval="1d",
    ):
        self.requested = list(symbols)
        return {
            symbol: self._frame(index)
            for index, symbol in enumerate(symbols)
        }, {}

    def observability_snapshot(self, symbols=None):
        return {
            "symbols": len(symbols or []),
            "primary": "FakeMarketData",
        }


def test_market_context_refresh_persists_breadth_and_regime():
    repository = FakeRepository()
    provider = FakeMarketData()
    service = MarketContextService(
        market_data=provider,
        universe=FakeUniverse(40),
        repository=repository,
    )

    result = service.refresh(limit=25)

    assert result["requested_symbols"] == 25
    assert result["analyzed_symbols"] == 25
    assert result["coverage_pct"] == 100.0
    assert result["breadth"]["advances"] == 25
    assert result["breadth"]["declines"] == 0
    assert result["breadth"]["above_ema50_pct"] == 100.0
    assert result["breadth"]["direction"] in {
        "BULLISH",
        "STRONG_BULLISH",
    }
    assert result["regime"]["regime"] in {
        "BULLISH",
        "SIDEWAYS",
        "HIGH_VOLATILITY",
        "RISK_OFF",
        "BEARISH",
    }
    assert result["regime"]["methodology"] == (
        "equal_weight_normalized_sample_composite"
    )
    assert set(repository.records) == {"breadth", "regime"}


def test_market_context_sampling_spans_full_universe():
    provider = FakeMarketData()
    service = MarketContextService(
        market_data=provider,
        universe=FakeUniverse(100),
        repository=FakeRepository(),
    )

    service.refresh(limit=25)

    assert provider.requested[0] == "S000"
    assert provider.requested[-1] == "S099"
    assert len(provider.requested) == 25


def test_market_context_snapshot_reports_not_available_before_refresh():
    service = MarketContextService(
        market_data=FakeMarketData(),
        universe=FakeUniverse(),
        repository=FakeRepository(),
    )

    result = service.snapshot("breadth")

    assert result["status"] == "not_available"
    assert result["kind"] == "breadth"


def test_market_context_snapshot_returns_persisted_payload():
    repository = FakeRepository()
    service = MarketContextService(
        market_data=FakeMarketData(),
        universe=FakeUniverse(),
        repository=repository,
    )
    service.refresh(limit=25)

    result = service.snapshot("regime")

    assert result["kind"] == "regime"
    assert result["snapshot_sample_size"] == 25
    assert result["snapshot_updated_at"]
