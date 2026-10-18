"""Weekend-capable, read-only daily-candle scanner and historical backtesting.

No broker orders, no simulated paper orders, no database mutation, no network
calls. The caller supplies completed daily candles with an explicit source.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
import math
import re
from typing import Any

import pandas as pd

from backtest.backtest_engine import BacktestConfig, BacktestEngine

IST = timezone(timedelta(hours=5, minutes=30))
COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")
MAX_CSV_BYTES = 8_000_000
MAX_SYMBOLS = 20
MIN_BARS = 80
STRATEGY = "R71-EMA20/50-RSI14-VOL20"


def last_completed_date(now: datetime | None = None) -> pd.Timestamp:
    """Conservative regular-session cutoff; never treats today's open bar as closed."""
    moment = now or datetime.now(IST)
    if moment.tzinfo is None:
        raise ValueError("now must have a timezone")
    moment = moment.astimezone(IST)
    cutoff = moment.date()
    if moment.weekday() >= 5 or (moment.hour, moment.minute) < (16, 0):
        cutoff -= timedelta(days=1)
    while cutoff.weekday() >= 5:
        cutoff -= timedelta(days=1)
    return pd.Timestamp(cutoff)


def normalize_symbol(symbol: Any) -> str:
    value = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9&._-]{1,24}", value):
        raise ValueError("Invalid NSE symbol")
    return value.removesuffix(".NS")


def parse_csv(content: bytes) -> dict[str, pd.DataFrame]:
    if not content or len(content) > MAX_CSV_BYTES:
        raise ValueError("CSV must be nonempty and at most 8 MB")
    try:
        data = pd.read_csv(BytesIO(content))
    except Exception as exc:
        raise ValueError("Unable to read OHLCV CSV") from exc
    data.columns = [str(column).strip().lower() for column in data.columns]
    if len(set(data.columns)) != len(data.columns):
        raise ValueError("Duplicate CSV column names")
    missing = set(COLUMNS) - set(data.columns)
    if missing:
        raise ValueError("Missing columns: " + ", ".join(sorted(missing)))
    if data.empty or len(data) > 25000:
        raise ValueError("CSV row count must be 1..25000")
    if data["symbol"].isna().any():
        raise ValueError("Symbol cannot be empty")
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if data["symbol"].nunique() > MAX_SYMBOLS:
        raise ValueError("Maximum 20 securities per research request")
    data["date"] = pd.to_datetime(data["date"], errors="coerce", utc=True)
    if data["date"].isna().any():
        raise ValueError("Invalid Date column")
    data["date"] = data["date"].dt.tz_convert(None).dt.normalize()
    if data.duplicated(["symbol", "date"]).any():
        raise ValueError("Duplicate symbol/date candles")
    result = {}
    for symbol, group in data.groupby("symbol", sort=True):
        result[symbol] = prepare_frame(group.set_index("date"), symbol=symbol)
    return result


def prepare_frame(source: pd.DataFrame, *, symbol: str = "") -> pd.DataFrame:
    """Validate OHLCV, dedupe only if distinct input timestamps, sort ascending."""
    if not isinstance(source, pd.DataFrame) or source.empty:
        raise ValueError("Empty historical candle series")
    frame = source.copy()
    frame.columns = [str(col).strip().lower() for col in frame.columns]
    if any(col not in frame.columns for col in ("open", "high", "low", "close", "volume")):
        raise ValueError("OHLCV candles are required")
    idx = pd.to_datetime(frame.index, errors="coerce", utc=True)
    if idx.isna().any():
        raise ValueError("Invalid candle timestamps")
    frame.index = idx.tz_convert(None).normalize()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate daily candles")
    frame = frame.sort_index()
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if not frame[col].map(math.isfinite).all():
            raise ValueError(f"Nonfinite {col} in {symbol}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"Nonpositive prices in {symbol}")
    if (frame["volume"] < 0).any():
        raise ValueError(f"Negative volume in {symbol}")
    if ((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) |
            (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError(f"Inconsistent OHLC in {symbol}")
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def completed_frame(frame: pd.DataFrame, *, now: datetime | None = None) -> pd.DataFrame:
    completed = last_completed_date(now)
    return prepare_frame(frame).loc[lambda df: df.index <= completed]


def indicators(candles: pd.DataFrame) -> pd.DataFrame:
    frame = prepare_frame(candles)
    close = frame["close"]
    frame["EMA_20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
    frame["EMA_50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    frame["RSI"] = (100.0 - (100.0 / (1.0 + rs))).where(loss != 0, 100.0)
    frame.loc[(gain == 0) & (loss == 0), "RSI"] = 50.0
    frame["VOLUME_MA20"] = frame["volume"].rolling(20, min_periods=20).mean()
    return frame


def cross_up(previous: pd.Series, current: pd.Series) -> bool:
    return (previous["EMA_20"] <= previous["EMA_50"] and
            current["EMA_20"] > current["EMA_50"])


def cross_down(previous: pd.Series, current: pd.Series) -> bool:
    return (previous["EMA_20"] >= previous["EMA_50"] and
            current["EMA_20"] < current["EMA_50"])


def qualified_entry(previous: pd.Series, current: pd.Series, *,
                    rsi_min: float = 60.0, proximity_pct: float = 1.0,
                    volume_filter: bool = True) -> bool:
    if current[["EMA_20", "EMA_50", "RSI", "VOLUME_MA20"]].isna().any():
        return False
    price_near = 100 * abs(current["close"] / current["EMA_20"] - 1) <= proximity_pct
    volume_ok = not volume_filter or current["volume"] > current["VOLUME_MA20"]
    return bool(cross_up(previous, current) and current["RSI"] >= rsi_min
                and price_near and volume_ok)


def scan_symbol(symbol: str, candles: pd.DataFrame, *,
                now: datetime | None = None, rsi_min: float = 60,
                proximity_pct: float = 1.0,
                volume_filter: bool = True) -> dict[str, Any]:
    frame = indicators(completed_frame(candles, now=now))
    if len(frame) < MIN_BARS:
        raise ValueError(f"{symbol}: requires at least {MIN_BARS} completed bars")
    current, prior = frame.iloc[-1], frame.iloc[-2]
    bullish = current["EMA_20"] > current["EMA_50"]
    rsi = float(current["RSI"])
    proximity = abs(float(current["close"] / current["EMA_20"]) - 1) * 100
    qualified = qualified_entry(prior, current, rsi_min=rsi_min,
                                proximity_pct=proximity_pct,
                                volume_filter=volume_filter)
    # A crossover only counts as a new signal if it occurred on the final
    # completed daily bar. Trending setups do not become new entries.
    classification = ("BUY_CROSS" if qualified else
                      "TREND_WATCH" if bullish and rsi >= rsi_min else
                      "NO_ENTRY")
    volume_ratio = float(current["volume"] / current["VOLUME_MA20"]) if current["VOLUME_MA20"] > 0 else 0.0
    score = (25 if bullish else 0) + (30 if qualified else 0) + (
        min(20, max(0, (rsi - 50) * 1.0))) + (
        15 if volume_ratio > 1 else 0) + (10 if proximity <= proximity_pct else 0)
    last_date = frame.index[-1].date()
    today = (now or datetime.now(IST)).astimezone(IST).date()
    stale = (today - last_date).days > 7
    return {
        "Symbol": normalize_symbol(symbol), "Classification": classification,
        "Score": round(float(score), 1), "Last completed bar": last_date.isoformat(),
        "Close": round(float(current["close"]), 2),
        "EMA20": round(float(current["EMA_20"]), 2),
        "EMA50": round(float(current["EMA_50"]), 2),
        "RSI14": round(rsi, 2), "Volume/MA20": round(volume_ratio, 2),
        "Distance to EMA20 (%)": round(proximity, 2),
        "Stale (>7 calendar days)": stale,
        "Entry signal": bool(qualified and not stale),
    }


def rank_candidates(series: dict[str, pd.DataFrame], *, now: datetime | None = None,
                    rsi_min: float = 60.0, proximity_pct: float = 1.0,
                    volume_filter: bool = True) -> tuple[pd.DataFrame, dict[str, str]]:
    if not 1 <= len(series) <= MAX_SYMBOLS:
        raise ValueError("Supply between 1 and 20 symbols")
    if not 0 <= rsi_min <= 100 or not 0 <= proximity_pct <= 20:
        raise ValueError("Invalid strategy thresholds")
    rows, errors = [], {}
    for symbol, candles in series.items():
        try:
            rows.append(scan_symbol(symbol, candles, now=now, rsi_min=rsi_min,
                                    proximity_pct=proximity_pct,
                                    volume_filter=volume_filter))
        except (ValueError, TypeError, KeyError) as exc:
            errors[str(symbol)] = str(exc)
    ranked = pd.DataFrame(rows)
    if not ranked.empty:
        ranked = ranked.sort_values(
            ["Entry signal", "Score", "Symbol"],
            ascending=[False, False, True],
        ).reset_index(drop=True)
    return ranked, errors


def backtest_symbol(symbol: str, candles: pd.DataFrame, *,
                    now: datetime | None = None,
                    initial_capital: float = 100000.0,
                    cost_bps: float = 10.0, slippage_bps: float = 10.0,
                    rsi_min: float = 60.0, proximity_pct: float = 1.0,
                    volume_filter: bool = True) -> dict[str, Any]:
    frame = indicators(completed_frame(candles, now=now))
    if len(frame) < MIN_BARS:
        raise ValueError("At least 80 completed daily bars required")
    if not 0 <= rsi_min <= 100 or not 0 <= proximity_pct <= 20:
        raise ValueError("Invalid thresholds")
    engine = BacktestEngine(BacktestConfig(
        initial_capital=initial_capital, cost_bps=cost_bps,
        slippage_bps=slippage_bps, force_final_exit=True,
    ))

    def entry(prev, current):
        return {"reason": "EMA20_50_RSI_VOL"} if qualified_entry(
            prev, current, rsi_min=rsi_min, proximity_pct=proximity_pct,
            volume_filter=volume_filter) else None

    def exit_rule(prev, current):
        if pd.isna(current["EMA_50"]) or pd.isna(current["RSI"]):
            return None
        if cross_down(prev, current):
            return {"reason": "EMA_CROSS_DOWN"}
        if current["RSI"] < rsi_min:
            return {"reason": "RSI_BELOW_THRESHOLD"}
        return None

    result = engine.run(frame, entry_rule=entry, exit_rule=exit_rule)
    return {
        "symbol": normalize_symbol(symbol),
        "strategy": STRATEGY,
        "as_of": frame.index[-1].date().isoformat(),
        "price_basis": "supplied_historical_daily_candles",
        "execution": BacktestEngine.EXECUTION_MODEL,
        "metrics": result.metrics,
        "trades": result.trades,
        "equity_curve": result.equity_curve,
    }
