"""Choose an observed common calendar without inventing OHLC candles."""

from backtest.portfolio_engine import SharedPortfolioEngine


def align_history(frames, *, minimum_bars=60):
    eligible, excluded = {}, []
    for symbol, frame in frames.items():
        try:
            normalized = SharedPortfolioEngine.align({symbol: frame})[symbol]
            if len(normalized) < minimum_bars:
                raise ValueError("Insufficient completed history")
            eligible[symbol] = normalized
        except (ValueError, TypeError):
            excluded.append(
                {
                    "symbol": symbol,
                    "reason": "insufficient_or_invalid_completed_history",
                }
            )
    while eligible:
        start = max(frame.index[0] for frame in eligible.values())
        end = min(frame.index[-1] for frame in eligible.values())
        trimmed = {symbol: frame.loc[start:end] for symbol, frame in eligible.items()}
        if min(len(frame) for frame in trimmed.values()) >= minimum_bars:
            break
        limiting = min(eligible, key=lambda s: (len(trimmed[s]), len(eligible[s]), s))
        eligible.pop(limiting)
        excluded.append(
            {"symbol": limiting, "reason": "insufficient_overlapping_history"}
        )
    if not eligible:
        raise ValueError(
            "Portfolio history is incomplete; no stock has 60 usable "
            "overlapping completed candles"
        )
    calendars = {}
    for symbol, frame in trimmed.items():
        calendars.setdefault(tuple(frame.index.asi8), []).append(symbol)
    # Missing interior bars can conceal stop hits. Keep the largest observed
    # calendar group; disclose exclusions rather than forward-filling or dropping
    # a real candle from another stock's position-management sequence.
    members = max(
        calendars.values(),
        key=lambda group: (len(group), len(trimmed[group[0]]), sorted(group)[0]),
    )
    aligned = {symbol: trimmed[symbol] for symbol in sorted(members)}
    for symbol in eligible:
        if symbol not in aligned:
            excluded.append(
                {"symbol": symbol, "reason": "interior_candle_calendar_mismatch"}
            )
    return aligned, {
        "method": "overlapping_window_observed_calendar_no_forward_fill",
        "included_symbols": sorted(aligned),
        "excluded_symbols": excluded,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "bars": len(next(iter(aligned.values()))),
    }
