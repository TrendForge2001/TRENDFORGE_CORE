"""Fetch and consume bounded history batches without retaining a full universe."""

from config.scanner_capacity import SCAN_BATCH_SIZE


def fetch_candle_batch(market_data, symbols, *, period, interval):
    """Retry up to three transient/omitted symbols once; keep the source unchanged."""
    from services.scanner_data_health import provider_detail

    frames, failures = market_data.batch_candles_with_errors(
        symbols, period=period, interval=interval
    )
    frames, failures = dict(frames), dict(failures)
    retried = 0
    for symbol in symbols:
        if frames.get(symbol) is not None:
            continue
        code = provider_detail(failures.get(symbol))["data_code"]
        if retried >= 3 or code not in {
            "DATA_TEMPORARILY_UNAVAILABLE",
            "BATCH_RESPONSE_INCOMPLETE",
        }:
            continue
        retried += 1
        retry, errors = market_data.batch_candles_with_errors(
            [symbol], period=period, interval=interval
        )
        if retry.get(symbol) is not None:
            frames[symbol] = retry[symbol]
            failures.pop(symbol, None)
        else:
            failures[symbol] = errors.get(symbol, failures.get(symbol))
    return frames, failures


def scan_candles(market_data, symbols, *, period, interval, progress=None):
    for offset in range(0, len(symbols), SCAN_BATCH_SIZE):
        chunk = symbols[offset : offset + SCAN_BATCH_SIZE]
        if progress is not None:
            progress(offset, len(symbols))
        frames, failures = fetch_candle_batch(
            market_data, chunk, period=period, interval=interval
        )
        # Provider caches and injected adapters may retain their mapping.
        frames = dict(frames)
        for symbol in chunk:
            yield symbol, frames.pop(symbol, None), failures.get(symbol)
