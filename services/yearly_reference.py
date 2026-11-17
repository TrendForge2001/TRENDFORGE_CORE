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
