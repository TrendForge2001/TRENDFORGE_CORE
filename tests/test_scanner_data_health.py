"""Source failures, listing warm-up and signals remain separate evidence."""

import pandas as pd

from services.candle_batches import fetch_candle_batch
from services.scanner_data_health import detail, provider_detail
from webapp.scanner_results import stock_view


def test_public_diagnostics_never_echo_provider_credentials():
    message = provider_detail("TokenException access_token=private token body")
    assert message["data_code"] == "KITE_AUTH_REQUIRED"
    assert "private" not in str(message)
    assert not message["retryable"]
    assert detail("WEEKLY_WARMUP_NOT_READY")["data_status"] == "WARMING_UP"


def test_retry_is_bounded_and_does_not_retry_auth_or_rate_limit():
    class Provider:
        def __init__(self):
            self.calls = []

        def batch_candles_with_errors(self, symbols, **kwargs):
            self.calls.append(list(symbols))
            if len(symbols) == 1:
                return {symbols[0]: pd.DataFrame({"close": [10]})}, {}
            return {}, {name: "timeout" for name in symbols} | {
                "AUTH": "TokenException",
                "RATE": "429",
            }

    provider = Provider()
    frames, failures = fetch_candle_batch(
        provider, ["A", "B", "C", "D", "AUTH", "RATE"], period="5y", interval="1d"
    )
    assert provider.calls == [["A", "B", "C", "D", "AUTH", "RATE"], ["A"], ["B"], ["C"]]
    assert set(frames) == {"A", "B", "C"}
    assert set(failures) == {"D", "AUTH", "RATE"}


def test_combined_view_does_not_convert_unknown_activity_to_buy():
    view = stock_view([{"symbol": "EXAMPLE", "signal": "WAIT"}])
    assert view.iloc[0]["Technical signal"] == "WAIT"
    assert view.iloc[0]["Institutional activity"] == "Unknown"
    assert pd.isna(view.iloc[0]["Rating /100"])


def test_weekly_missing_history_preserves_specific_source_failure():
    from types import SimpleNamespace

    from services.weekly_floor_research import WeeklyFloorResearch
    from tests.support.weekly_floor_candles import NOW

    market = SimpleNamespace(
        batch_candles_with_errors=lambda *a, **k: (
            {},
            {"EXAMPLE": "TokenException private-data"},
        )
    )
    technical = SimpleNamespace(
        market_data=market, _period=lambda *a: (None, "2y"), _symbols=list
    )
    result = WeeklyFloorResearch(technical)._history(
        ["EXAMPLE"], "positional", "2y", NOW, None, None
    )
    errors = result[5]
    assert errors[0]["data_code"] == "KITE_AUTH_REQUIRED"
    assert errors[0]["data_status"] == "UNAVAILABLE"
    assert "private-data" not in str(errors)


def test_partition_failure_identifies_failed_child_without_exception_body():
    from services.research_failure import ResearchPartitionFailed, failure_diagnostic

    child_id = "batch-" + "a" * 32 + "-p003"
    result = failure_diagnostic(
        ResearchPartitionFailed(
            {"batch_id": child_id, "error_code": "research_history_unavailable"}
        ),
        "partitions",
    )
    assert result["code"] == "research_partition_failed"
    assert result["phase"] == "partitions"
    assert result["child_batch_id"] == child_id
    assert result["child_error_code"] == "research_history_unavailable"
