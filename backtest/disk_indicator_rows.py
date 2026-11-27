"""Sequential indicator replay from private worker scratch storage."""

import gzip
import json
from pathlib import Path

from backtest.indicator_rows import IndicatorRow


class DiskIndicatorRows:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.files = {}

    def stage(self, symbol, frame):
        path = self.directory / f"indicators-{len(self.files)}.gz"
        columns = list(frame.columns)
        with gzip.open(path, "wt", compresslevel=1) as output:
            for row in frame.itertuples(index=True, name=None):
                output.write(
                    json.dumps([row[0].value, *row[1:]], separators=(",", ":")) + "\n"
                )
        self.files[symbol] = path, columns

    def rows(self, symbol, index):
        path, columns = self.files[symbol]
        with gzip.open(path, "rt") as source:
            for stamp in index:
                for line in source:
                    ns, *values = json.loads(line)
                    if ns < stamp.value:
                        continue
                    if ns == stamp.value:
                        yield IndicatorRow(stamp, columns, values)
                        break
                    raise ValueError("Staged candle timestamp mismatch")
                else:
                    raise ValueError("Staged candle history incomplete")
