"""Completed-week gap recovery and prior-calendar-year Floor pivots."""

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from indicators.ema_pivot import wilder_average
from scanner.portfolio_policy import number, risk_details

STRATEGY_ID = "tf_weekly_gap_recovery_ema50_100_floor"
VERSION = "weekly-floor-gap-recovery-v1"
TZ = ZoneInfo("Asia/Kolkata")
INDICATORS = (
    "EMA_50",
    "EMA_100",
    "RSI_WILDER_14",
    "MACD",
    "MACD_SIGNAL",
    "VOL_EMA_30",
    "PREVIOUS_CLOSE",
    "PREVIOUS_BODY_MIDPOINT",
    "FLOOR_YEAR_P",
    "FLOOR_YEAR_R1",
    "FLOOR_YEAR_R2",
    "FLOOR_YEAR_S1",
    "FLOOR_YEAR_S2",
)


def local_now(now=None):
    stamp = pd.Timestamp(now or datetime.now(TZ))
    return stamp.tz_localize(TZ) if stamp.tzinfo is None else stamp.tz_convert(TZ)


def daily_history(frame, *, now=None):
    from backtest.portfolio_engine import SharedPortfolioEngine

    out = SharedPortfolioEngine.align({"STOCK": frame})["STOCK"].copy()
    dates = out.index.normalize()
    if dates.has_duplicates:
        raise ValueError("Weekly research requires one observed candle per session")
    out.index = dates + pd.Timedelta(hours=9, minutes=15)
    volume = pd.to_numeric(out.get("volume"), errors="coerce")
    if (
        not isinstance(volume, pd.Series)
        or not np.isfinite(volume).all()
        or (volume < 0).any()
    ):
        raise ValueError("Finite nonnegative daily volume is required")
    out["volume"] = volume.to_numpy()
    closed = dates + pd.Timedelta(hours=15, minutes=30) <= local_now(now)
    out = out.loc[closed, ["open", "high", "low", "close", "volume"]]
    if len(out) < 2:
        raise ValueError("Insufficient completed daily history")
    return out


def yearly_pivots(daily):
    """Only reference an observed, bounded preceding year; never current H/L/C."""
    levels = {}
    for offset, (year, group) in enumerate(daily.groupby(daily.index.year)):
        first = pd.offsets.BDay().rollforward(pd.Timestamp(year, 1, 1))
        last = pd.offsets.BDay().rollback(pd.Timestamp(year, 12, 31))
        if (
            offset == 0
            or len(group) < 200
            or group.index[0].date() > first.date()
            or group.index[-1].date() < last.date()
        ):
            continue
        high, low, close = (
            float(group.high.max()),
            float(group.low.min()),
            float(group.close.iloc[-1]),
        )
        pivot = (high + low + close) / 3
        levels[int(year) + 1] = {
            "FLOOR_YEAR_P": pivot,
            "FLOOR_YEAR_R1": 2 * pivot - low,
            "FLOOR_YEAR_R2": pivot + high - low,
            "FLOOR_YEAR_S1": 2 * pivot - high,
            "FLOOR_YEAR_S2": pivot - high + low,
        }
    return levels


def weekly_indicators(daily, *, now=None):
    daily = daily.copy(deep=False)
    daily.index = pd.DatetimeIndex(pd.to_datetime(daily.index, utc=True)).tz_convert(TZ)
    keys = daily.index.tz_localize(None).to_period("W-SUN")
    out = daily.groupby(keys).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    out.index = pd.DatetimeIndex(out.index.end_time.floor("s")).tz_localize(TZ)
    # The first observed week may be truncated. Confirm only at calendar-week
    # end, including special weekend sessions without future-calendar knowledge.
    out = out.iloc[1:]
    out = out.loc[out.index <= local_now(now)].copy()
    if out.empty:
        raise ValueError("No completed weekly candles")
    out["EMA_50"] = out.close.ewm(span=50, adjust=False, min_periods=50).mean()
    out["EMA_100"] = out.close.ewm(span=100, adjust=False, min_periods=100).mean()
    delta = out.close.diff()
    gain, loss = (
        wilder_average(delta.clip(lower=0)),
        wilder_average(-delta.clip(upper=0)),
    )
    out["RSI_WILDER_14"] = (100 - 100 / (1 + gain / loss)).where(
        (gain != 0) | (loss != 0), 50.0
    )
    out["MACD"] = (
        out.close.ewm(span=12, adjust=False).mean()
        - out.close.ewm(span=26, adjust=False).mean()
    )
    out["MACD_SIGNAL"] = out.MACD.ewm(span=9, adjust=False).mean()
    out["VOL_EMA_30"] = out.volume.ewm(span=30, adjust=False, min_periods=30).mean()
    out["PREVIOUS_CLOSE"] = out.close.shift()
    out["PREVIOUS_BODY_MIDPOINT"] = (out.open.shift() + out.close.shift()) / 2
    gaps = out.index.to_series().diff().dt.days.ne(7).cumsum()
    out["WEEKLY_WARMUP"] = out.groupby(gaps).cumcount() + 1
    annual = yearly_pivots(daily)
    for column in INDICATORS:
        if column.startswith("FLOOR_YEAR_"):
            out[column] = [
                annual.get(stamp.year, {}).get(column, np.nan) for stamp in out.index
            ]
    return out, annual


def weekly_signal(row, *, tick_size=0.05, pivots=None):
    if number(tick_size) is None or not 0 < tick_size <= 100:
        raise ValueError("Invalid research tick size")
    row = row.copy()
    if pivots is not None:
        for key in INDICATORS:
            if key.startswith("FLOOR_YEAR_"):
                row[key] = pivots.get(key, np.nan)
    required = ("open", "high", "low", "close", "volume", *INDICATORS)
    if row.get("WEEKLY_WARMUP", 0) < 100 or any(
        number(row.get(key)) is None for key in required
    ):
        raise ValueError(
            "Need 100 completed weekly candles and complete previous-year Floor pivots"
        )
    checks = {
        "ema50_above_ema100": row.EMA_50 > row.EMA_100,
        "close_above_ema50": row.close > row.EMA_50,
        "open_below_previous_close": row.open < row.PREVIOUS_CLOSE,
        "close_above_previous_body_midpoint": row.close > row.PREVIOUS_BODY_MIDPOINT,
        "bullish_recovery_candle": row.close > row.open,
        "volume_above_ema30": row.volume > row.VOL_EMA_30,
        "rsi_above_50": row.RSI_WILDER_14 > 50,
        "macd_above_signal": row.MACD > row.MACD_SIGNAL,
    }
    stop = round((math.floor(float(row.low) / tick_size) - 1) * tick_size, 10)
    risk = risk_details(row.close, stop, row.FLOOR_YEAR_R2)
    target_reached = row.close >= row.FLOOR_YEAR_R2
    signal = (
        "SELL"
        if target_reached
        else "BUY"
        if all(checks.values()) and risk.get("reward_risk") is not None
        else "HOLD"
    )
    return {
        "signal": signal,
        "score": round(sum(checks.values()) / len(checks) * 100, 2),
        "risk": {
            "entry": float(row.close),
            "stoploss": stop,
            "target2": float(row.FLOOR_YEAR_R2),
            **risk,
        },
        "checks": {key: bool(value) for key, value in checks.items()},
        "indicators": {
            key: float(row[key]) for key in (*INDICATORS, "volume", "close")
        },
        "signal_semantics": "SELL exits an existing long; HOLD means no fresh action",
    }
