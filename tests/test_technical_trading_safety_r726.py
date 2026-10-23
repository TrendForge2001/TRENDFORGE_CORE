"""Technical research errors and candle timing must not bypass paper admission."""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from services import technical_trading_service as technical

IST = ZoneInfo("Asia/Kolkata")
SECRET = secrets.token_hex(16)


def frame(end="2026-10-19 09:45", *, rows=70, freq="15min"):
    return pd.DataFrame(
        {name: [100.0] * rows for name in ("open", "high", "low", "close", "volume")},
        index=pd.date_range(end=end, periods=rows, freq=freq, tz=IST),
    )


class Market:
    def __init__(self, candles=None, missing=False):
        self.frame = candles if candles is not None else frame()
        self.missing = missing

    def batch_candles_with_errors(self, symbols, **_):
        return (
            {} if self.missing else {symbol: self.frame.copy() for symbol in symbols},
            {symbol: SECRET for symbol in symbols},
        )

    def observability_snapshot(self, _):
        return {
            "provider_counts": {"KiteProvider": 1, SECRET: 99},
            "fallback_count": 0,
            "provider_errors_by_symbol": {"ABC": [SECRET]},
            "circuit_events": [{"error": SECRET}],
            "circuit_breakers": {"KiteProvider": {"last_error": SECRET}},
        }


class Indicators:
    def calculate(self, candles):
        return candles.copy()


class Paper:
    def __init__(self):
        self.calls = []

    def process_scan(self, result, **kwargs):
        self.calls.append((result, kwargs))
        return {"status": "not_requested", "opened": []}


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(
        technical,
        "latest_signal",
        lambda *_: {
            "signal": "BUY",
            "score": 90.0,
            "confidence": 90.0,
            "trigger": "CROSS",
            "risk": {"entry": 100.0, "stoploss": 95.0, "target2": 110.0},
            "evidence": {},
            "indicators": {},
        },
    )
    return technical.TechnicalTradingService(
        market_data=Market(),
        paper_auto_entry=Paper(),
        repository=object(),
        indicator_engine=Indicators(),
    )


def test_provider_failures_and_diagnostics_are_sanitized(service, caplog):
    service.market_data.missing = True
    result = service.scan(symbols=["ABC"], mode="intraday")
    row = result["results"][0]
    assert row["error_code"] == "MARKET_DATA_UNAVAILABLE"
    assert "Kite candle data is unavailable" in row["error"]
    assert re.fullmatch(r"[0-9a-f]{12}", row["error_reference"])
    assert row["error_reference"] in caplog.text
    assert SECRET not in json.dumps(result) + caplog.text
    assert result["provider_observation"] == {
        "provider_counts": {"KiteProvider": 1},
        "fallback_count": 0,
        "provider_error_count": 1,
    }
    assert row["execution_eligible"] is False


def test_readiness_does_not_forward_provider_diagnostic_payloads(service):
    service.market_data.health = lambda: {
        "status": "degraded",
        "provider": "MarketDataAdapter",
        "last_error": SECRET,
        "runtime_status": "failed",
        "max_workers": 4,
        "provider_health": {
            "status": "degraded",
            "error": SECRET,
            "provider_health": {
                "KiteProvider": {"status": "degraded", "auth_error": SECRET}
            },
        },
        "circuit_breakers": {"KiteProvider": {"last_error": SECRET}},
    }
    result = service.readiness()
    assert SECRET not in json.dumps(result)
    assert result["market_data"]["status"] == "degraded"
    assert result["market_data"]["provider_health"]["status"] == "degraded"
    assert result["market_data"]["max_workers"] == 4


def test_indicator_value_error_is_not_exposed_as_safe_validation(service, caplog):
    def fail(_):
        raise ValueError(SECRET)

    service.indicators.calculate = fail
    result = service.scan(symbols=["ABC"], mode="intraday")
    row = result["results"][0]
    assert row["error_code"] == "TECHNICAL_ANALYSIS_FAILED"
    assert row["error"].startswith("Technical analysis failed (reference:")
    assert "error_type=ValueError" in caplog.text
    assert SECRET not in json.dumps(result) + caplog.text


def test_known_candle_validation_stays_useful_and_safe(service):
    service.market_data.frame = frame(rows=5)
    result = service.scan(symbols=["ABC"], mode="intraday")
    row = result["results"][0]
    assert row["error_code"] == "TECHNICAL_VALIDATION_FAILED"
    assert row["error"] == "At least 60 completed candles are required"


@pytest.mark.parametrize("index", [pd.RangeIndex(2), ["bad", "timestamps"], [pd.NaT]])
def test_invalid_candle_timestamps_fail_closed(index):
    candles = pd.DataFrame({"close": range(len(index))}, index=index)
    with pytest.raises(
        technical.TechnicalTradingValidationError, match="valid timestamps"
    ):
        technical.TechnicalTradingService._completed_bars(candles, interval="15m")


def test_duplicate_candles_are_rejected():
    candles = frame(rows=2)
    candles.index = [candles.index[0], candles.index[0]]
    with pytest.raises(
        technical.TechnicalTradingValidationError, match="duplicate timestamps"
    ):
        technical.TechnicalTradingService._completed_bars(candles, interval="15m")


def test_every_incomplete_or_future_intraday_bar_is_removed():
    candles = frame("2026-10-19 11:00", rows=5)
    completed = technical.TechnicalTradingService._completed_bars(
        candles,
        interval="15m",
        now=datetime(2026, 10, 19, 10, 30, tzinfo=IST),
    )
    assert list(completed.index) == list(candles.index[:2])
    assert completed.index[-1].hour == 10 and completed.index[-1].minute == 15


@pytest.mark.parametrize(("hour", "expected_rows"), [(14, 1), (16, 2)])
def test_daily_completion_drops_all_future_dates(hour, expected_rows):
    candles = frame("2026-10-21", rows=4, freq="D")
    completed = technical.TechnicalTradingService._completed_bars(
        candles,
        interval="1d",
        now=datetime(2026, 10, 19, hour, tzinfo=IST),
    )
    assert len(completed) == expected_rows
    assert completed.index[-1].day == (18 if hour < 15 else 19)


@pytest.mark.parametrize("as_utc", [False, True])
def test_current_completed_intraday_bar_remains_paper_eligible(service, as_utc):
    now = datetime(2026, 10, 19, 10, 0, tzinfo=IST)
    if as_utc:
        service.market_data.frame.index = service.market_data.frame.index.tz_convert(
            "UTC"
        )
        now = now.astimezone(ZoneInfo("UTC"))
    result = service.scan(symbols=["ABC"], mode="intraday", now=now, execute_paper=True)
    assert result["buy_candidates"] == 1
    assert result["top_picks"][0]["execution_eligible"] is True
    assert result["top_picks"][0]["execution_blocked_reason"] is None
    assert service.paper_auto_entry.calls[0][0]["execution_top_picks"]


def test_indicator_output_must_still_contain_a_current_bar(service):
    service.indicators.calculate = lambda candles: candles.iloc[:-1].copy()
    result = service.scan(
        symbols=["ABC"],
        mode="intraday",
        now=datetime(2026, 10, 19, 10, 0, tzinfo=IST),
    )
    assert result["results"][0]["signal"] == "BUY"
    assert result["results"][0]["execution_blocked_reason"] == "stale_candles"
    assert result["buy_candidates"] == 0


@pytest.mark.parametrize(("minute", "expected"), [(29, False), (30, True)])
def test_first_intraday_bar_admits_only_after_0930(service, minute, expected):
    service.market_data.frame = frame("2026-10-19 09:15")
    result = service.scan(
        symbols=["ABC"],
        mode="intraday",
        now=datetime(2026, 10, 19, 9, minute, tzinfo=IST),
    )
    assert result["results"][0]["execution_eligible"] is expected


def test_a_preopen_bar_does_not_qualify_as_a_current_intraday_candle(service):
    service.market_data.frame = frame("2026-10-19 09:00")
    result = service.scan(
        symbols=["ABC"],
        mode="intraday",
        now=datetime(2026, 10, 19, 9, 20, tzinfo=IST),
    )
    assert result["results"][0]["execution_eligible"] is False
    assert result["results"][0]["execution_blocked_reason"] == "invalid_session_candle"


@pytest.mark.parametrize(
    ("bar", "now", "reason"),
    [
        (
            "2026-10-16 15:00",
            datetime(2026, 10, 19, 10, 0, tzinfo=IST),
            "stale_candles",
        ),
        (
            "2026-10-19 09:30",
            datetime(2026, 10, 19, 10, 0, tzinfo=IST),
            "stale_candles",
        ),
        (
            "2026-10-19 14:30",
            datetime(2026, 10, 19, 14, 45, tzinfo=IST),
            "intraday_entry_window_closed",
        ),
        (
            "2026-10-17 09:45",
            datetime(2026, 10, 17, 10, 0, tzinfo=IST),
            "intraday_entry_window_closed",
        ),
    ],
)
def test_stale_or_late_intraday_buy_is_research_only(service, bar, now, reason):
    service.market_data.frame = frame(bar)
    result = service.scan(symbols=["ABC"], mode="intraday", now=now, execute_paper=True)
    row = result["results"][0]
    assert row["signal"] == "BUY"
    assert row["execution_eligible"] is False
    assert row["execution_blocked_reason"] == reason
    assert result["buy_candidates"] == 0
    assert service.paper_auto_entry.calls[0][0]["execution_top_picks"] == []


@pytest.mark.parametrize(("hour", "eligible"), [(10, True), (16, False)])
def test_friday_daily_bar_is_current_on_monday_until_close(service, hour, eligible):
    service.market_data.frame = frame("2026-10-16", freq="D")
    result = service.scan(
        symbols=["ABC"],
        mode="swing",
        now=datetime(2026, 10, 19, hour, tzinfo=IST),
    )
    assert result["results"][0]["execution_eligible"] is eligible
    assert result["results"][0]["execution_blocked_reason"] == (
        None if eligible else "stale_candles"
    )


@pytest.mark.parametrize(
    "kwargs", [{"mode": "unknown"}, {"mode": "swing", "period": "invalid"}]
)
def test_local_request_errors_use_trusted_validation_class(service, kwargs):
    with pytest.raises(technical.TechnicalTradingValidationError):
        service.scan(symbols=["ABC"], **kwargs)
