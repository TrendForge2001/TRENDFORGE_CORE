"""Bound cloud preview work; accepted runs retain the complete universe."""

from core.deployment_role import on_render

CLOUD_MAX_CANDLE_ROWS = 150_000
CLOUD_BATCH_CANDLE_ROWS = 50_000
CLOUD_BATCH_SYMBOLS = 50
ESTIMATED_BARS = {"30d": 550, "45d": 825, "60d": 1100, "1y": 270, "2y": 540, "5y": 1350}


def validate_backtest_capacity(settings, count):
    estimate = count * ESTIMATED_BARS[settings["period"]]
    if on_render() and estimate > CLOUD_MAX_CANDLE_ROWS:
        raise ValueError(
            "This full-list backtest exceeds this cloud service's compute limit. "
            "Run it in the PC workspace for the complete universe and "
            "its separate local report archive."
        )


class ResearchCapacityExceeded(RuntimeError):
    """Observed candle volume exceeded the admitted worker budget."""


def research_partitions(symbols, settings, strategies):
    """Independent stock/strategy portfolios; never aggregate their capital/P&L."""
    size = len(symbols)
    if on_render():
        size = min(
            CLOUD_BATCH_SYMBOLS,
            # Reserve headroom for inclusive dates and warm-up candles.
            (CLOUD_BATCH_CANDLE_ROWS * 9 // 10) // ESTIMATED_BARS[settings["period"]],
        )
    if not size or not strategies:
        raise ValueError("Choose stocks and strategies before starting research")
    partitions = [
        {"symbols": symbols[offset : offset + size], "settings": strategy}
        for strategy in strategies
        for offset in range(0, len(symbols), size)
    ]
    if len(partitions) > 256:
        raise ValueError(
            "Select fewer strategies: a campaign supports at most "
            "256 sequential batches"
        )
    return partitions
