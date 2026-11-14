"""History scope survives admission; reference downloads cannot enable trades."""

import io
import json
import zipfile

import pytest

from scanner.strategy_horizons import horizon_strategy
from scanner.strategy_registry import list_strategies
from services.research_batches import ResearchBatchManager
from tests import test_research_batches as batch_support
from tests.test_research_batches import finish, request
from webapp.scanner_reference import condition_rows, reference_pack, reference_zip

technical = batch_support.technical


@pytest.mark.parametrize("period", ["1y", "2y", "5y"])
def test_requested_period_reaches_history_provider_and_saved_report(technical, period):
    seen = []
    original = technical.market_data.batch_candles_with_errors

    def history(symbols, **kwargs):
        seen.append(kwargs["period"])
        return original(symbols, **kwargs)

    technical.market_data.batch_candles_with_errors = history
    manager = ResearchBatchManager(technical, import_history=False)
    try:
        batch = finish(manager, manager.submit("backtest", request(period=period)))
        assert batch["status"] == "completed"
        assert seen == [period]
        assert batch["request"]["settings"]["period"] == period
        assert batch["report"]["period"] == period
    finally:
        manager.close(wait=True)


@pytest.mark.parametrize(
    "horizon,strategy,period",
    [
        ("intraday", "tf_ema9_26_bullish_pivot", "5y"),
        ("short_swing", "tf_ema9_26_bullish_pivot", "60d"),
        ("long_term", "tf_ema100_200_bullish_pivot", "1y"),
    ],
)
def test_incompatible_period_is_rejected(horizon, strategy, period):
    with pytest.raises(ValueError, match="period"):
        horizon_strategy(horizon, strategy, period)


def test_public_reference_pack_is_source_linked_and_separate_from_execution_catalog():
    pack = reference_pack()
    templates = pack["templates"]
    assert len(templates) == 6
    ids = {row["strategy_id"] for row in list_strategies()}
    assert all(
        row["id"] not in ids and row["execution_enabled"] is False for row in templates
    )
    assert all(
        row["source_url"].startswith("https://") and row["limitations"]
        for row in templates
    )
    assert {row["platform"] for row in templates} == {"Streak", "Screener.in"}
    with zipfile.ZipFile(io.BytesIO(reference_zip())) as archive:
        assert json.loads(archive.read("public_templates.json")) == pack
        assert (
            len([name for name in archive.namelist() if name.startswith("templates/")])
            == 6
        )
        assert archive.read("scanner_conditions.csv").startswith(b"\xef\xbb\xbf")
    assert {row["Strategy ID"] for row in condition_rows()} == {
        "tf_weekly_gap_recovery_ema50_100_floor"
    }
