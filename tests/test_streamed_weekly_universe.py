"""Exact account parity and full-universe scans without retaining price matrices."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backtest.weekly_account_data import DiskAccountData
from backtest.weekly_account_engine import simulate_account
from scanner.weekly_account_policy import COMPARISONS
from scanner.weekly_floor import STRATEGY_ID
from services.research_batches import ResearchBatchManager
from services.weekly_floor_research import WeeklyFloorResearch
from tests import test_weekly_floor_research as support
from tests.support.weekly_floor_candles import NOW, ExampleMarket

technical = support.technical


@pytest.mark.parametrize("policy", COMPARISONS)
def test_disk_source_matches_reference_account_with_ragged_stock_calendars(policy):
    daily, weeks, annual = support.prepared()
    frames = {
        "A": daily,
        "B": daily.iloc[500:].drop(daily.index[800]),
        "C": daily.iloc[300:],
    }
    weekly, years = {s: weeks for s in frames}, {s: annual for s in frames}
    expected = simulate_account(frames, weekly, years, policy)
    with DiskAccountData() as source:
        folder = Path(source.folder.name)
        for symbol in reversed(list(frames)):
            source.add(symbol, frames[symbol], weekly[symbol], years[symbol])
        actual = simulate_account(None, None, None, policy, source=source)
        assert actual == expected
        assert source.observed_rows == sum(len(f) for f in frames.values())
    assert not folder.exists()


def test_disk_scratch_is_removed_after_failure():
    with pytest.raises(ValueError), DiskAccountData() as source:
        folder = Path(source.folder.name)
        raise ValueError("test-only")
    assert not folder.exists()


def test_full_500_stock_scan_returns_one_complete_report_in_small_fetches(technical):
    class Market(ExampleMarket):
        sizes = []

        def batch_candles_with_errors(self, symbols, **kwargs):
            self.sizes.append(len(symbols))
            return super().batch_candles_with_errors(symbols, **kwargs)

    technical.market_data = Market()
    result = WeeklyFloorResearch(technical).scan(
        symbols=[f"S{i:03d}" for i in range(500)], mode="positional", now=NOW, top_n=500
    )
    assert len(result["results"]) == result["completed_symbols"] == 500
    assert result["error_symbols"] == 0
    assert len({r["symbol"] for r in result["results"]}) == 500
    assert max(technical.market_data.sizes) <= 25
    assert sum(technical.market_data.sizes) == 500
    assert len(result["history_alignment"]["coverage"]) == 500


def test_500_stock_backtest_uses_one_disk_account_not_independent_partitions(
    technical, monkeypatch
):
    technical.market_data = ExampleMarket(frame=ExampleMarket().frame.iloc[-200:])
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setattr(
        "services.weekly_floor_research.local_now", lambda now=None: NOW
    )
    monkeypatch.setattr(
        "services.weekly_account_research.local_now", lambda now=None: NOW
    )
    monkeypatch.setattr(
        "backtest.weekly_account_data.MemoryAccountData",
        lambda *a, **k: pytest.fail("Must stream full-universe prices"),
    )
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        batch = manager.submit(
            "backtest",
            {
                "symbols": [f"S{i:03d}" for i in range(500)],
                "strategy_id": STRATEGY_ID,
                "horizon": "long_term",
                "stock_list": "NIFTY 500",
                "period": "5y",
            },
        )
        manager.futures[batch["batch_id"]].result(timeout=120)
        saved = manager.repository.get(batch["batch_id"])
        assert saved["status"] == "completed", saved.get("diagnostic")
        assert "partitions" not in saved["request"]
        assert saved["request"]["max_candle_rows"] == 1500000
        assert len(saved["report"]["history_alignment"]["coverage"]) == 500
        assert len(saved["report"]["comparisons"]) == 4
        assert all(
            r["initial_capital"] == 100000 for r in saved["report"]["comparisons"]
        )
    finally:
        manager.close(wait=True)


def test_campaign_is_explicit_and_consumed_once(technical, monkeypatch):
    from services.research_campaign import request_research_campaign

    technical.market_data = ExampleMarket(frame=ExampleMarket().frame.iloc[-200:])
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-db1tb7jncjis73c994e0")
    monkeypatch.setenv(
        "TRENDFORGE_RESEARCH_CAMPAIGN",
        json.dumps(
            {"request_id": "test-capacity", "stock_list": "NIFTY 500", "period": "5y"}
        ),
    )
    monkeypatch.setattr(
        "services.research_campaign.official_symbols", lambda name: ["A", "B"]
    )
    monkeypatch.setattr(
        "services.weekly_floor_research.local_now", lambda now=None: NOW
    )
    monkeypatch.setattr(
        "services.weekly_account_research.local_now", lambda now=None: NOW
    )
    manager = ResearchBatchManager(technical, import_history=False, isolated=False)
    try:
        app = SimpleNamespace(
            state=SimpleNamespace(research_manager_getter=lambda: manager)
        )
        ids = request_research_campaign(app)
        assert len(ids) == 2
        for batch_id in ids:
            manager.futures[batch_id].result(timeout=30)
            assert manager.repository.get(batch_id)["status"] == "completed"
        assert request_research_campaign(app) is None
        assert len(manager.futures) == 2
    finally:
        manager.close(wait=True)
