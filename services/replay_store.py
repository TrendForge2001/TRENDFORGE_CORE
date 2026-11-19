"""Private compact replay inputs; cached data never enables paper entries."""

import hashlib
import json
import os
import shutil
import sqlite3
import zlib
from collections import OrderedDict

import numpy as np
import pandas as pd


class ReplayStorageFull(RuntimeError):
    pass


class ReplayStore:
    def __init__(self, journal):
        self.root = journal.path.parent / (journal.path.stem + "-replay")
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        self.connection = sqlite3.connect(self.root / "events.sqlite")
        os.chmod(self.root / "events.sqlite", 0o600)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS signals(mode TEXT,stamp TEXT,symbol TEXT,"
            "offset INTEGER,payload BLOB,due TEXT,PRIMARY KEY(mode,stamp,symbol))"
        )
        self.connection.execute(
            "CREATE INDEX IF NOT EXISTS signal_time ON signals(due,mode)"
        )
        self.cache = OrderedDict()
        self.price_cache = OrderedDict()

    def path(self, kind, symbol):
        return self.root / (
            hashlib.sha256((kind + ":" + symbol).encode()).hexdigest() + ".npz"
        )

    def save(self, kind, symbol, frame):
        if shutil.disk_usage(self.root).free < 96 * 1024**2:
            raise ReplayStorageFull("Insufficient private checkpoint disk headroom")
        numeric = [
            str(c) for c in frame.select_dtypes(include=["number", "bool"]).columns
        ]
        extra = {
            name: np.asarray(
                [json.dumps(list(v), separators=(",", ":")) for v in frame[name]],
                dtype=str,
            )
            for name in ("SWING_HIGHS_20", "SWING_LOWS_20")
            if name in frame
        }
        path = self.path(kind, symbol)
        temporary = path.with_suffix(".partial")
        with temporary.open("wb") as output:
            index = (
                frame.index.tz_localize("Asia/Kolkata")
                if frame.index.tz is None
                else frame.index
            )
            np.savez_compressed(
                output,
                stamps=index.as_unit("ns").asi8,
                columns=np.asarray(numeric, dtype=str),
                values=frame[numeric].to_numpy(dtype=float),
                **extra,
            )
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        temporary.replace(path)

    def load(self, kind, symbol):
        path = self.path(kind, symbol)
        if not path.exists():
            return None
        with np.load(path, allow_pickle=False) as data:
            frame = pd.DataFrame(
                data["values"],
                columns=data["columns"].tolist(),
                index=pd.to_datetime(data["stamps"], utc=True).tz_convert(
                    "Asia/Kolkata"
                ),
            )
            for name in ("SWING_HIGHS_20", "SWING_LOWS_20"):
                if name in data:
                    frame[name] = [tuple(json.loads(s)) for s in data[name]]
        return frame

    def frame(self, kind, symbol):
        key = kind, symbol
        if key not in self.cache:
            value = self.load(kind, symbol)
            if value is None:
                raise ValueError("Replay inputs are unavailable")
            self.cache[key] = value
        self.cache.move_to_end(key)
        while len(self.cache) > 6:
            self.cache.popitem(last=False)
        return self.cache[key]

    def save_signals(self, mode, symbol, signals, start, frame):
        values = []
        for stamp, source in signals.items():
            if stamp < start or not source["evaluations"]:
                continue
            value = {
                name: source[name] for name in ("consensus", "consensus_score", "count")
            }
            value["strategy_ids"] = list(source["evaluations"])
            evaluation = next(iter(source["evaluations"].values()))
            value["signal_row"] = evaluation["entry_plan"]["signal_evidence"]
            offset = source["offset"]
            if offset + 1 >= len(frame):
                continue
            due = (
                stamp + pd.Timedelta(minutes=15)
                if mode == "intraday"
                else frame.index[offset + 1].normalize()
                + pd.Timedelta(hours=9, minutes=30)
            )
            values.append(
                (
                    mode,
                    stamp.isoformat(),
                    symbol,
                    offset,
                    zlib.compress(
                        json.dumps(value, default=str, allow_nan=False).encode()
                    ),
                    due.isoformat(),
                )
            )
        with self.connection:
            self.connection.execute(
                "DELETE FROM signals WHERE mode=? AND symbol=?", (mode, symbol)
            )
            self.connection.executemany(
                "INSERT INTO signals VALUES(?,?,?,?,?,?)", values
            )

    def events(self, due):
        for mode, stamp, symbol, offset, payload in self.connection.execute(
            "SELECT mode,stamp,symbol,offset,payload FROM signals "
            "WHERE due=? ORDER BY mode,symbol",
            (due.isoformat(),),
        ):
            yield {
                "mode": mode,
                "stamp": pd.Timestamp(stamp),
                "symbol": symbol,
                "offset": offset,
                **json.loads(zlib.decompress(payload)),
            }

    def quote_frame(self, symbol):
        if symbol not in self.price_cache:
            value = self.load("quotes", symbol)
            if value is None:
                return None
            self.price_cache[symbol] = value
        self.price_cache.move_to_end(symbol)
        while len(self.price_cache) > 64:
            self.price_cache.popitem(last=False)
        return self.price_cache[symbol]

    def calendar(self, symbols):
        arrays = []
        for symbol in symbols:
            path = self.path("quotes", symbol)
            if path.exists():
                with np.load(path, allow_pickle=False) as data:
                    arrays.append(data["stamps"])
        if not arrays:
            raise ValueError("No observed execution calendar available")
        return pd.to_datetime(np.unique(np.concatenate(arrays)), utc=True).tz_convert(
            "Asia/Kolkata"
        )

    def coverage(self, symbols):
        from collections import Counter

        result = Counter()
        for symbol in symbols:
            path = self.path("quotes", symbol)
            if path.exists():
                with np.load(path, allow_pickle=False) as data:
                    result.update(data["stamps"].tolist())
        return result

    def close(self):
        self.cache.clear()
        self.price_cache.clear()
        self.connection.close()
