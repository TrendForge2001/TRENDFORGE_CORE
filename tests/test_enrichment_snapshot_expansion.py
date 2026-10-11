from __future__ import annotations

import json

from providers.enrichment_snapshot_provider import (
    has_sector_signal_evidence,
)
from scripts.enrichment_snapshot import (
    expand_nifty500_snapshot,
    verify_nifty500_snapshot,
)


class FakeUniverseProvider:
    def __init__(self, count=501):
        self.count = count
        self.calls = 0

    def nifty500(self, force_refresh=False):
        self.calls += 1
        members = [
            {
                "symbol": f"SYM{i}",
                "name": f"Company {i}",
                "sector": (
                    "Financial Services"
                    if i % 2 == 0
                    else "Information Technology"
                ),
                "exchange": "NSE",
            }
            for i in range(self.count)
        ]
        return {
            "index": "NIFTY 500",
            "source": "NSE_NIFTY500_CSV",
            "source_url": "https://example.test/nifty500.csv",
            "nominal_company_count": 500,
            "security_count": self.count,
            "count_variance": self.count - 500,
            "fetched_at": "2026-10-11T00:00:00+00:00",
            "source_last_modified":
                "Sun, 11 Oct 2026 00:00:00 GMT",
            "source_etag": '"fixture"',
            "members": members,
        }

    def health(self):
        return {
            "status": "runtime_verified",
            "provider": "FakeUniverseProvider",
        }


class FakeCorporateProvider:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0
        self.last_symbols = []

    def get_many(self, symbols, days=120):
        self.calls += 1
        self.last_symbols = list(symbols)
        if self.fail:
            raise RuntimeError("corporate upstream blocked")
        return {
            symbol: (
                [
                    {
                        "symbol": symbol,
                        "title": "Dividend",
                        "type": "Dividend",
                    }
                ]
                if symbol == "SYM0"
                else []
            )
            for symbol in symbols
        }

    def health(self):
        return {
            "status": (
                "degraded"
                if self.fail
                else "runtime_verified"
            )
        }


class FakeSectorProvider:
    def __init__(self, signal_for_even=True):
        self.signal_for_even = signal_for_even
        self.calls = []

    def get_from_classification(
        self,
        symbol,
        *,
        sector,
        industry="",
        metadata_source="supplied",
        source_errors=None,
        allow_classification_only=False,
    ):
        self.calls.append(
            (
                symbol,
                sector,
                metadata_source,
                allow_classification_only,
            )
        )
        index = int(symbol.removeprefix("SYM"))
        payload = {
            "sector": sector,
            "industry": industry,
            "_meta": {
                "metadata_source": metadata_source,
                "signal_evidence": False,
            },
        }
        if self.signal_for_even and index % 2 == 0:
            payload.update(
                {
                    "change_1d": 1.0,
                    "change_1w": 2.0,
                    "change_1m": 3.0,
                    "market_return": 1.0,
                }
            )
            payload["_meta"]["signal_evidence"] = True
        return payload

    def health(self):
        return {"status": "runtime_verified"}


class FakeBigSharkProvider:
    def __init__(self):
        self.calls = 0

    def get(self, symbol):
        self.calls += 1
        return {
            "shareholding_snapshot": {
                "fii": 10.0,
                "dii": 20.0,
                "public": 70.0,
            }
        }

    def health(self):
        return {"status": "configured"}


def _base_snapshot(tmp_path):
    path = tmp_path / "base.json"
    payload = {
        "schema_version": 1,
        "generated_at": "2026-10-10T00:00:00+00:00",
        "symbols": {
            "SYM0": {
                "big_shark": {
                    "shareholding_snapshot": {
                        "fii": 12.0,
                        "dii": 18.0,
                    }
                }
            },
            "STALE": {
                "big_shark": {
                    "shareholding_snapshot": {
                        "fii": 5.0,
                    }
                }
            },
        },
        "failures": {},
    }
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def test_expand_nifty500_snapshot_covers_all_source_securities(tmp_path):
    output = tmp_path / "expanded.json"
    universe = FakeUniverseProvider(501)
    corporate = FakeCorporateProvider()
    sector = FakeSectorProvider()
    big_shark = FakeBigSharkProvider()

    result = expand_nifty500_snapshot(
        output,
        base_snapshot=_base_snapshot(tmp_path),
        universe_provider=universe,
        corporate_provider=corporate,
        sector_provider=sector,
        big_shark_provider=big_shark,
        include_big_shark=False,
        pause_seconds=0,
    )

    assert result["status"] == "expanded"
    assert result["security_count"] == 501
    assert result["production_fields_complete"] is True
    assert result["coverage"]["corporate_actions"] == 501
    assert result["coverage"]["sector"] == 501
    assert result["signal_coverage"]["sector"] == 251
    assert corporate.calls == 1
    assert len(corporate.last_symbols) == 501
    assert big_shark.calls == 0

    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert len(bundle["symbols"]) == 501
    assert "STALE" not in bundle["symbols"]
    assert bundle["symbols"]["SYM0"]["big_shark"][
        "shareholding_snapshot"
    ]["fii"] == 12.0
    assert bundle["symbols"]["SYM1"]["corporate_actions"] == []
    assert bundle["universe"]["security_count"] == 501


def test_verify_nifty500_snapshot_requires_corporate_and_sector_coverage(
    tmp_path,
):
    output = tmp_path / "expanded.json"
    expand_nifty500_snapshot(
        output,
        universe_provider=FakeUniverseProvider(501),
        corporate_provider=FakeCorporateProvider(),
        sector_provider=FakeSectorProvider(),
        big_shark_provider=FakeBigSharkProvider(),
    )

    result = verify_nifty500_snapshot(output)

    assert result["status"] == "production_ready"
    assert result["production_ready"] is True
    assert result["security_count"] == 501
    assert result["corporate_actions_complete"] is True
    assert result["sector_complete"] is True
    assert result["sector_signal_coverage"] == 251


def test_expand_nifty500_snapshot_fails_closed_on_bulk_corporate_error(
    tmp_path,
):
    output = tmp_path / "partial.json"

    result = expand_nifty500_snapshot(
        output,
        universe_provider=FakeUniverseProvider(500),
        corporate_provider=FakeCorporateProvider(fail=True),
        sector_provider=FakeSectorProvider(),
        big_shark_provider=FakeBigSharkProvider(),
    )

    assert result["status"] == "partial"
    assert result["production_fields_complete"] is False
    assert result["coverage"]["corporate_actions"] == 0
    assert result["coverage"]["sector"] == 500
    assert "corporate_actions" in result["global_failures"]

    verified = verify_nifty500_snapshot(output)
    assert verified["status"] == "incomplete"
    assert verified["production_ready"] is False
    assert verified["corporate_actions_complete"] is False


def test_sector_classification_is_evidence_without_invented_signal_data():
    classification_only = {
        "sector": "Diversified",
        "industry": "Diversified",
        "_meta": {
            "metadata_source": "NSE_NIFTY500_CSV",
            "signal_evidence": False,
        },
    }

    assert has_sector_signal_evidence(
        classification_only
    ) is False
    assert has_sector_signal_evidence(
        {
            **classification_only,
            "change_1m": 2.5,
        }
    ) is True
