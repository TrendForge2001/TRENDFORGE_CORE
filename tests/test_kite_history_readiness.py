"""Separate data access, completed history and indicator failures without leaks."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from indicators.daily_reference import attach_daily_reference
from indicators.indicator_engine import IndicatorEngine
from providers.kite_errors import PermissionException
from services.kite_trading_readiness import kite_trading_readiness

# Historical execution regression; revised public rules have dedicated coverage.
pytestmark = pytest.mark.usefixtures("previous_exit_policy")

NOW = datetime(2026, 11, 16, 10, 15, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def candles():
    stamps = pd.DatetimeIndex(
        [
            day.to_pydatetime() + timedelta(minutes=9 * 60 + 15 + 15 * bar)
            for day in pd.bdate_range("2026-10-01", "2026-11-13", tz="Asia/Kolkata")
            for bar in range(25)
        ]
    )
    x = np.arange(len(stamps))
    price = 200 + x * 0.02 + np.sin(x / 5)
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 1,
            "low": price - 1,
            "close": price + 0.25,
            "volume": 10000 + (x % 12) * 100,
        },
        index=stamps,
    )


def check(frame):
    broker = SimpleNamespace(
        health=lambda: {"authenticated": True}, candles=lambda *args, **kwargs: frame
    )
    return kite_trading_readiness(broker, probe_history=True, now=NOW)


def test_complete_data_and_real_indicator_pipeline_pass(candles):
    report = check(candles)
    assert report["history_status"] == "available"
    assert report["indicator_status"] == "calculated"
    assert report["history_completed_candles"] == len(candles)
    assert report["history_diagnostic"] is None


def test_history_permissions_are_identified_without_provider_error_text():
    def denied(*args, **kwargs):
        raise PermissionException("private broker response and credentials")

    broker = SimpleNamespace(health=lambda: {"authenticated": True}, candles=denied)
    report = kite_trading_readiness(broker, probe_history=True, now=NOW)
    assert report["history_diagnostic"] == {
        "stage": "history_request",
        "code": "history_access_denied",
    }
    assert report["history_status"] == "unavailable_or_invalid"
    assert "private" not in str(report)


def test_insufficient_candles_remain_blocked_with_observed_count(candles):
    report = check(candles.tail(12))
    assert report["history_completed_candles"] == 12
    assert report["history_diagnostic"]["code"] == "insufficient_completed_candles"
    assert report["history_status"] != "available"


def test_indicator_failure_does_not_claim_history_retrieval_failed(
    candles, monkeypatch
):
    def fail(self, frame):
        raise ValueError("private provider fields")

    monkeypatch.setattr(IndicatorEngine, "calculate", fail)
    report = check(candles)
    assert report["history_status"] == "available"
    assert report["indicator_status"] == "unavailable"
    assert report["history_diagnostic"] == {
        "stage": "indicators",
        "code": "indicator_calculation_failed",
    }
    assert "private" not in str(report)


def test_missing_indicator_names_and_session_coverage_are_explicit(
    candles, monkeypatch
):
    calculate = IndicatorEngine.calculate

    def incomplete(self, frame):
        output = calculate(self, frame)
        output.loc[output.index[-1], "TRAD_DAY_P"] = float("nan")
        return output

    monkeypatch.setattr(IndicatorEngine, "calculate", incomplete)
    report = check(candles)
    assert report["history_missing_indicators"] == ["TRAD_DAY_P"]
    assert report["history_session_counts"] == [{"normal": 25, "other": 0}] * 2
    assert report["history_diagnostic"]["code"] == "indicator_history_incomplete"


def test_real_daily_reference_completes_all_required_values_for_24_bar_sessions(
    candles,
):
    daily = candles.groupby(candles.index.normalize()).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    missing_close = candles.loc[
        ~((candles.index.hour == 15) & (candles.index.minute == 15))
    ]
    before = check(missing_close)
    assert before["history_missing_indicators"] == [
        "TRAD_DAY_P",
        "TRAD_DAY_R1",
        "TRAD_DAY_R2",
        "TRAD_DAY_S1",
        "TRAD_DAY_S2",
    ]
    attached = attach_daily_reference(missing_close, daily, now=NOW)
    report = check(attached)
    assert report["indicator_status"] == "calculated"
    assert report["history_missing_indicators"] == []
    assert report["history_required_indicator_count"] == 28
    assert report["history_pivot_reference_source"] == "kite_completed_daily"
    assert report["history_completed_candles"] == len(missing_close)


def test_older_recovered_session_does_not_mislabel_latest_incomplete_reference(candles):
    daily = candles.groupby(candles.index.normalize()).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    daily.loc[daily.index[-2], "high"] = float("nan")
    missing_close = candles.loc[
        ~((candles.index.hour == 15) & (candles.index.minute == 15))
    ]
    report = check(attach_daily_reference(missing_close, daily, now=NOW))
    assert report["indicator_status"] == "unavailable"
    assert report["history_pivot_reference_source"] == "incomplete_intraday_session"
