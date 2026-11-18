"""Small daily-reference cache; intraday samples cannot stand in for a year."""

from collections import OrderedDict
from threading import RLock

from indicators.yearly_fibonacci import annual_levels, attach_levels
from scanner.weekly_floor import daily_history, local_now


class YearlyReferenceCache:
    def __init__(self):
        self._levels = OrderedDict()
        self._lock = RLock()

    def enrich(self, frame, *, market_data, symbol, interval, now=None):
        if interval == "1d":
            return attach_levels(frame, annual_levels(daily_history(frame, now=now)))
        key = (symbol, local_now(now).date())
        with self._lock:
            levels = self._levels.get(key)
        fetched_rows = 0
        if levels is None:
            batch, _ = market_data.batch_candles_with_errors(
                [symbol], period="5y", interval="1d"
            )
            raw = batch.get(symbol)
            if raw is None:
                raise ValueError(
                    "Daily history unavailable for yearly Fibonacci references"
                )
            daily = daily_history(raw, now=now)
            fetched_rows = len(daily)
            levels = annual_levels(daily)
            with self._lock:
                self._levels[key] = levels
                self._levels.move_to_end(key)
                while len(self._levels) > 1024:
                    self._levels.popitem(last=False)
        out = attach_levels(frame, levels)
        out.attrs["annual_reference_rows"] = fetched_rows
        return out

    def enrich_approved(self, frame, *, market_data, symbol, interval, now=None):
        import pandas as pd

        from indicators.approved_strategies import (
            add_native,
            attach_references,
            reference_maps,
        )

        rows = 0
        if interval == "1d":
            maps = reference_maps(daily_history(frame, now=now))
        else:
            observed = local_now(now)
            start = min(
                local_now(frame.index[0]), observed - pd.Timedelta(days=180)
            ) - pd.Timedelta(days=40)
            key = ("approved", symbol, observed.date())
            with self._lock:
                cached = self._levels.get(key)
            maps = (
                cached["maps"] if cached and cached["start"] <= start.date() else None
            )
            if maps is None:
                batch, _ = market_data.batch_candles_with_errors(
                    [symbol], period="5y", interval="1d"
                )
                raw = batch.get(symbol)
                if raw is None:
                    raise ValueError(
                        "Daily reference history unavailable for approved pivot rules"
                    )
                daily = daily_history(raw, now=now)
                rows = len(daily)
                maps = reference_maps(daily)
                # Retain only the current native window plus reference headroom,
                # not five years of per-day dictionaries for every universe stock.
                for period, freq in (("DAY", "D"), ("WEEK", "W-SUN"), ("MONTH", "M")):
                    cutoff = (
                        start.tz_localize(None).to_period(freq).ordinal - 1
                        if start.tzinfo
                        else start.to_period(freq).ordinal - 1
                    )
                    maps[period] = {
                        k: v for k, v in maps[period].items() if k >= cutoff
                    }
                with self._lock:
                    self._levels[key] = {"maps": maps, "start": start.date()}
                    self._levels.move_to_end(key)
                    while len(self._levels) > 1024:
                        self._levels.popitem(last=False)
        out = add_native(attach_references(frame, maps))
        out.attrs["annual_reference_rows"] = rows
        return out


def enrich_broker_approved(frame, broker, *, symbol, interval, now=None):
    """Read-only adapter used by operator indicator checks."""
    from types import SimpleNamespace

    from providers.market_data_adapter import MarketDataAdapter

    def batch(symbols, *, period, interval):
        normalized = {}
        for item in symbols:
            normalized[item] = MarketDataAdapter._normalize(
                item, broker.candles(item, period=period, interval=interval)
            )
        return normalized, {}

    return YearlyReferenceCache().enrich_approved(
        frame,
        market_data=SimpleNamespace(batch_candles_with_errors=batch),
        symbol=symbol,
        interval=interval,
        now=now,
    )
