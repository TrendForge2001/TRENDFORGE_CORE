"""Bounded temporary price storage; fetch chunks never own portfolio capital."""

import json
import os
import sqlite3
import tempfile
from collections import namedtuple
from pathlib import Path

import pandas as pd

from scanner.weekly_floor import weekly_signal

Bar = namedtuple("Bar", "open high low close")


def entry_events(symbol, frame, weeks, annual, *, tick_size=0.05, start=None):
    for signal_at, row in weeks.iterrows():
        offset = frame.index.searchsorted(signal_at, side="right")
        if offset >= len(frame):
            continue
        stamp = frame.index[offset]
        if stamp - signal_at > pd.Timedelta(days=10) or (
            start is not None and stamp < start
        ):
            continue
        try:
            signal = weekly_signal(
                row, tick_size=tick_size, pivots=annual.get(stamp.year, {})
            )
        except ValueError:
            continue
        if signal["signal"] == "BUY":
            yield stamp, symbol, signal_at, signal


class MemoryAccountData:
    """Reference adapter for existing callers and exact disk-path comparisons."""

    def __init__(self, frames, weekly, annual, *, tick_size=0.05):
        self.observations, self.signals = {}, {}
        for symbol in sorted(frames):
            frame = frames[symbol]
            for row in frame.itertuples():
                self.observations.setdefault(row.Index, {})[symbol] = row
            for stamp, event_symbol, signal_at, signal in entry_events(
                symbol, frame, weekly[symbol], annual[symbol], tick_size=tick_size
            ):
                self.signals.setdefault(stamp, []).append(
                    (event_symbol, signal_at, signal)
                )

    def calendar(self, start=None):
        dates = pd.DatetimeIndex(sorted(self.observations))
        return dates[dates >= start] if start is not None else dates

    def rows(self, stamp):
        return self.observations[stamp]

    def events(self, stamp):
        return self.signals.get(stamp, [])


class DiskAccountData:
    """One session at a time from a disposable, indexed SQLite database."""

    def __init__(self, *, tick_size=0.05):
        self.folder = tempfile.TemporaryDirectory(
            prefix="tf-weekly-prices-", dir=os.getenv("TRENDFORGE_RESEARCH_SCRATCH_DIR")
        )
        self.connection = sqlite3.connect(str(Path(self.folder.name) / "prices.db"))
        self.connection.execute("PRAGMA cache_size=-4096")
        self.connection.execute("PRAGMA mmap_size=0")
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute(
            "CREATE TABLE prices (stamp INTEGER, symbol TEXT, opening REAL, "
            "high REAL, low REAL, closing REAL, "
            "PRIMARY KEY(stamp,symbol)) WITHOUT ROWID"
        )
        self.connection.execute(
            "CREATE TABLE events (stamp INTEGER, symbol TEXT, signal_at TEXT, "
            "payload TEXT, PRIMARY KEY(stamp,symbol)) WITHOUT ROWID"
        )
        self.tick_size = tick_size
        self.symbols = []
        self.observed_rows = 0

    def add(self, symbol, frame, weeks, annual):
        # Keep only one stock's indicator frame during staging, not 500 frames.
        self.connection.executemany(
            "INSERT INTO prices VALUES (?,?,?,?,?,?)",
            (
                (
                    int(row.Index.value),
                    symbol,
                    float(row.open),
                    float(row.high),
                    float(row.low),
                    float(row.close),
                )
                for row in frame.itertuples()
            ),
        )
        self.connection.executemany(
            "INSERT INTO events VALUES (?,?,?,?)",
            (
                (
                    int(stamp.value),
                    symbol,
                    signal_at.isoformat(),
                    json.dumps(signal, allow_nan=False),
                )
                for stamp, symbol, signal_at, signal in entry_events(
                    symbol, frame, weeks, annual, tick_size=self.tick_size
                )
            ),
        )
        self.connection.commit()
        self.symbols.append(symbol)
        self.observed_rows += len(frame)

    def calendar(self, start=None):
        lower = int(start.value) if start is not None else 0
        values = [
            row[0]
            for row in self.connection.execute(
                "SELECT DISTINCT stamp FROM prices WHERE stamp>=? ORDER BY stamp",
                (lower,),
            )
        ]
        return pd.DatetimeIndex(pd.to_datetime(values, utc=True)).tz_convert(
            "Asia/Kolkata"
        )

    def rows(self, stamp):
        return {
            row[0]: Bar(*row[1:])
            for row in self.connection.execute(
                "SELECT symbol,opening,high,low,closing FROM prices "
                "WHERE stamp=? ORDER BY symbol",
                (int(stamp.value),),
            )
        }

    def events(self, stamp):
        return [
            (symbol, pd.Timestamp(signal_at), json.loads(payload))
            for symbol, signal_at, payload in self.connection.execute(
                "SELECT symbol,signal_at,payload FROM events "
                "WHERE stamp=? ORDER BY symbol",
                (int(stamp.value),),
            )
        ]

    def close(self):
        self.connection.close()
        self.folder.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
