from __future__ import annotations

import hashlib
import json

import pytest

from providers.enrichment_snapshot_provider import (
    EnrichmentSnapshot,
    EnrichmentSnapshotError,
    SnapshotFieldProvider,
)
from reconstruction.enrichment import StockEnricher
from reconstruction.provider_registry import ProviderRegistry
from scripts.enrichment_snapshot import verify_snapshot


def write_snapshot(tmp_path):
    payload = {
        "schema_version": 1,
        "generated_at": "2026-10-08T23:00:00+05:30",
        "symbols": {
            "ABC": {
                "corporate_actions": [],
                "big_shark": {
                    "deals": [
                        {
                            "side": "BUY",
                            "value_crore": 25.0,
                            "buyer": "Institution A",
                        }
                    ]
                },
                "sector": {
                    "sector": "Healthcare",
                    "proxy_symbol": "^CNXPHARMA",
                    "change_1d": 1.1,
                    "change_1m": 3.4,
                    "market_return": 2.0,
                },
            }
        },
        "failures": {},
    }
    path = tmp_path / "snapshot.json"
    raw = (
        json.dumps(payload, indent=2, sort_keys=True)
        + "\n"
    ).encode("utf-8")
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def test_snapshot_loads_and_verifies_sha(tmp_path):
    path, digest = write_snapshot(tmp_path)

    snapshot = EnrichmentSnapshot(
        path,
        expected_sha256=digest,
    )

    assert snapshot.symbol_count() == 1
    assert snapshot.field_count("sector") == 1
    assert snapshot.get("sector", "abc")["sector"] == "Healthcare"
    assert snapshot.health()["pinned_sha256"] is True


def test_snapshot_rejects_wrong_sha(tmp_path):
    path, _ = write_snapshot(tmp_path)

    with pytest.raises(
        EnrichmentSnapshotError,
        match="SHA256 mismatch",
    ):
        EnrichmentSnapshot(
            path,
            expected_sha256="0" * 64,
        )


def test_snapshot_field_provider_returns_none_for_missing_symbol(tmp_path):
    path, _ = write_snapshot(tmp_path)
    snapshot = EnrichmentSnapshot(path)
    provider = SnapshotFieldProvider(snapshot, "sector")

    assert provider.get("XYZ") is None
    assert provider.get("ABC")["proxy_symbol"] == "^CNXPHARMA"


def test_snapshot_empty_corporate_actions_is_a_valid_resolved_value(tmp_path):
    path, _ = write_snapshot(tmp_path)
    snapshot = EnrichmentSnapshot(path)

    class FailingLiveProvider:
        def __init__(self):
            self.calls = 0

        def get(self, symbol, payload=None):
            self.calls += 1
            raise AssertionError("live provider must not be called")

    fallback = FailingLiveProvider()
    registry = ProviderRegistry()
    registry.register(
        "corporate_actions",
        SnapshotFieldProvider(snapshot, "corporate_actions"),
        priority=10,
    )
    registry.register(
        "corporate_actions",
        fallback,
        priority=100,
    )

    enricher = StockEnricher(registry=registry)
    result = enricher.enrich(
        {
            "symbol": "ABC",
            "fundamentals": {},
            "big_shark": {},
            "sector": {},
        }
    )

    assert result.data["corporate_actions"] == []
    assert fallback.calls == 0


def test_snapshot_missing_symbol_falls_through_to_live_provider(tmp_path):
    path, _ = write_snapshot(tmp_path)
    snapshot = EnrichmentSnapshot(path)

    class LiveProvider:
        def __init__(self):
            self.calls = 0

        def get(self, symbol, payload=None):
            self.calls += 1
            return {"sector": "Technology"}

    fallback = LiveProvider()
    registry = ProviderRegistry()
    registry.register(
        "sector",
        SnapshotFieldProvider(snapshot, "sector"),
        priority=10,
    )
    registry.register(
        "sector",
        fallback,
        priority=100,
    )

    enricher = StockEnricher(registry=registry)
    result = enricher.enrich(
        {
            "symbol": "XYZ",
            "fundamentals": {},
            "corporate_actions": [],
            "big_shark": {},
        }
    )

    assert result.data["sector"] == {"sector": "Technology"}
    assert fallback.calls == 1


def test_snapshot_verify_cli_contract(tmp_path):
    path, digest = write_snapshot(tmp_path)

    result = verify_snapshot(
        path,
        expected_sha256=digest,
    )

    assert result["status"] == "verified"
    assert result["symbols"] == 1
    assert result["coverage"] == {
        "corporate_actions": 1,
        "big_shark": 1,
        "sector": 1,
    }
