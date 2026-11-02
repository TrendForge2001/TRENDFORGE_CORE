"""Fetch and consume bounded history batches without retaining a full universe."""

from config.scanner_capacity import SCAN_BATCH_SIZE


def scan_candles(market_data, symbols, *, period, interval, progress=None):
    for offset in range(0, len(symbols), SCAN_BATCH_SIZE):
        chunk = symbols[offset : offset + SCAN_BATCH_SIZE]
        if progress is not None:
            progress(offset, len(symbols))
        frames, failures = market_data.batch_candles_with_errors(
            chunk, period=period, interval=interval
        )
        # Provider caches and injected adapters may retain their mapping.
        frames = dict(frames)
        for symbol in chunk:
            yield symbol, frames.pop(symbol, None), failures.get(symbol)
