from __future__ import annotations

from universe.nifty500 import Nifty500Universe


def _payload(count: int = 500):
    return {
        "source": "NSE_NIFTY500_CSV",
        "source_url": "https://example.invalid/nifty500.csv",
        "fetched_at": "2026-10-10T00:00:00+00:00",
        "source_last_modified": "Fri, 09 Oct 2026 12:00:00 GMT",
        "invalid_rows": 0,
        "duplicate_symbols": [],
        "members": [
            {
                "symbol": f"SYM{i}",
                "name": f"Company {i}",
                "sector": "Industrials",
                "exchange": "NSE",
                "isin": f"INE{i:09d}",
                "series": "EQ",
            }
            for i in range(count)
        ],
    }


def test_universe_refresh_retains_source_metadata_and_500_contract():
    universe = Nifty500Universe(
        loader=lambda **_: _payload(500)
    )

    members = universe.refresh()

    assert len(members) == 500
    health = universe.health()
    assert health["status"] == "healthy"
    assert health["count"] == 500
    assert health["expected_count"] == 500
    assert health["source"] == "NSE_NIFTY500_CSV"
    assert health["fetched_at"] == "2026-10-10T00:00:00+00:00"
    assert health["duplicate_symbols"] == []
    assert health["invalid_rows"] == 0


def test_universe_degrades_instead_of_padding_partial_membership():
    universe = Nifty500Universe()
    universe.load(_payload(499))

    assert len(universe.symbols()) == 499
    assert universe.health()["status"] == "degraded"


def test_universe_normalizes_and_deduplicates_members():
    universe = Nifty500Universe()
    universe.load(
        [
            {"symbol": " abc.ns ", "name": "A"},
            {"symbol": "ABC", "name": "Duplicate"},
            {"symbol": " xyz ", "name": "X"},
        ]
    )

    assert universe.symbols() == ["ABC", "XYZ"]
    health = universe.health()
    assert health["duplicate_symbols"] == ["ABC"]
    assert health["count"] == 2
    assert health["status"] == "degraded"


def test_ensure_loaded_does_not_refetch_without_refresh():
    calls = []

    def loader(**kwargs):
        calls.append(kwargs)
        return _payload(500)

    universe = Nifty500Universe(loader=loader)
    universe.ensure_loaded()
    universe.ensure_loaded()

    assert len(calls) == 1

    universe.ensure_loaded(refresh=True)
    assert len(calls) == 2
    assert calls[-1]["force_refresh"] is True
