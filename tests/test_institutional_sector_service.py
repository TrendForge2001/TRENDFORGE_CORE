from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from services.institutional_sector_service import (
    InstitutionalSectorService,
)


class FakeRepository:
    def __init__(self):
        self.rows = {}

    def save(
        self,
        kind,
        snapshot_key,
        payload,
        *,
        universe=None,
        sample_size=None,
    ):
        row = {
            "kind": kind,
            "snapshot_key": snapshot_key,
            "universe": universe,
            "sample_size": sample_size,
            "created_at": "2026-10-16T10:00:00+00:00",
            "payload": dict(payload),
        }
        self.rows[(kind, snapshot_key)] = row
        return dict(row)

    def get(self, kind, snapshot_key):
        row = self.rows.get((kind, snapshot_key))
        return dict(row) if row else None

    def list(self, *, kind, limit=100):
        return [
            dict(row)
            for (row_kind, _), row in self.rows.items()
            if row_kind == kind
        ][:limit]

    def count(self, *, kind):
        return sum(
            1
            for row_kind, _ in self.rows
            if row_kind == kind
        )

    def close(self):
        pass


class FakeInstitutionalProvider:
    def __init__(self):
        self.calls = []

    def get(self, symbol, payload=None):
        self.calls.append(symbol)
        return {
            "shareholding_snapshot": {
                "promoter": 52.0,
                "fii": 12.0,
                "dii": 10.0,
                "mutual_fund": 6.0,
            },
            "holding_changes": [
                {
                    "name": "Foreign funds",
                    "category": "FII",
                    "change": 1.5,
                    "value_crore": 100,
                },
                {
                    "name": "Domestic funds",
                    "category": "DII",
                    "change": 0.8,
                    "value_crore": 80,
                },
            ],
            "promoter": {
                "current": 52.0,
                "previous": 51.5,
                "pledge": 0.0,
            },
            "deals": [
                {
                    "side": "BUY",
                    "value_crore": 60,
                    "client_name": "Large Fund",
                }
            ],
            "_meta": {
                "shareholding_source": "NSE",
                "nse_shareholding_runtime_verified": True,
            },
        }

    def health(self):
        return {
            "status": "runtime_verified",
            "classification": "conservative",
        }


@dataclass
class Member:
    symbol: str
    sector: str


class FakeUniverse:
    def __init__(self):
        self.values = [
            Member(
                symbol=f"S{i:03d}",
                sector="TECH" if i < 30 else "BANK",
            )
            for i in range(60)
        ]

    def ensure_loaded(self, refresh=False):
        return list(self.values)


class FakeMarketData:
    def begin_observation(self):
        pass

    @staticmethod
    def _frame(index):
        dates = pd.date_range(
            "2026-01-01",
            periods=100,
            freq="D",
        )
        positive = index < 30
        step = 0.8 if positive else -0.15
        close = pd.Series(
            [100.0 + step * i for i in range(100)],
            index=dates,
        )
        volume = pd.Series(
            [
                1_000_000
                + (20_000 if positive else -5_000) * i
                for i in range(100)
            ],
            index=dates,
        )
        volume = volume.clip(lower=100_000)
        return pd.DataFrame(
            {
                "open": close - 0.2,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": volume,
            },
            index=dates,
        )

    def batch_candles_with_errors(
        self,
        symbols,
        period="1y",
        interval="1d",
    ):
        frames = {
            symbol: self._frame(int(symbol[1:]))
            for symbol in symbols
        }
        return frames, {}

    def observability_snapshot(self, symbols=None):
        return {
            "provider": "fake",
            "symbols": len(symbols or []),
        }


def build_service():
    return InstitutionalSectorService(
        institutional_provider=FakeInstitutionalProvider(),
        market_data=FakeMarketData(),
        universe=FakeUniverse(),
        repository=FakeRepository(),
    )


def test_institutional_refresh_uses_big_shark_engine_and_persists():
    service = build_service()

    result = service.refresh_institutional(
        symbols=["tcs", "TCS"],
    )

    assert result["requested_symbols"] == 1
    assert result["completed_symbols"] == 1
    snapshot = service.institutional("TCS")
    assert snapshot["status"] == "ready"
    assert snapshot["score"] > 0
    assert snapshot["confidence"] > 0
    assert snapshot["ownership"]["fii"] == 12.0
    assert snapshot["provider_evidence"][
        "shareholding_source"
    ] == "NSE"
    assert snapshot["trade_signal"] is False


def test_institutional_latest_ranks_by_score():
    service = build_service()
    service.refresh_institutional(symbols=["TCS", "INFY"])

    latest = service.institutional_latest(limit=10)

    assert latest["returned"] == 2
    assert {
        row["symbol"]
        for row in latest["snapshots"]
    } == {"TCS", "INFY"}


def test_sector_strength_ranks_positive_sector_above_negative():
    service = build_service()

    result = service.refresh_sector_strength(
        limit=60,
        period="1y",
        interval="1d",
    )

    assert result["status"] == "ready"
    assert result["coverage_pct"] == 100.0
    assert result["sector_count"] == 2
    assert result["sectors"][0]["sector"] == "TECH"
    assert result["sectors"][0]["score"] > result[
        "sectors"
    ][1]["score"]
    assert (
        result["institutional_sector_flow_available"]
        is False
    )
    assert all(
        row["institutional_sector_flow_available"]
        is False
        for row in result["sectors"]
    )

    persisted = service.sector_strength()
    assert persisted["snapshot_sample_size"] == 60
    assert persisted["sectors"][0]["rank"] == 1


def test_readiness_declares_diagnostic_not_trade_signal():
    readiness = build_service().readiness()

    assert readiness["trade_signal"] is False
    assert readiness["institutional_engine"] == "Big Shark Engine"
    assert readiness["sector_engine"] == "Sector Engine"
