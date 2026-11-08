"""Two causal indicator rows per stock without per-candle pandas allocations."""


class IndicatorRow(dict):
    def __init__(self, stamp, columns, values):
        super().__init__(zip(columns, values, strict=True))
        self.name = stamp


def indicator_rows(frame, columns):
    selected = [column for column in dict.fromkeys(columns) if column in frame]
    for values in frame[selected].itertuples(index=True, name=None):
        yield IndicatorRow(values[0], selected, values[1:])
