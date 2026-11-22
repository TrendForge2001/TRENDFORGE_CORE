"""Current scanner/entry scope; persisted positions keep their exit lineage."""

PAUSED_HORIZONS = frozenset({"intraday", "short_swing"})


def active_modes():
    from scanner.strategy_registry import list_strategies

    return tuple(
        mode
        for mode in ("intraday", "swing", "positional")
        if list_strategies(mode=mode)
    )


def effective_modes(values=None):
    available = active_modes()
    output = []
    for value in values or available:
        mode = str(value or "").strip().lower()
        if mode not in {"intraday", "swing", "positional"}:
            raise ValueError("modes must contain only intraday, swing or positional")
        if mode in available and mode not in output:
            output.append(mode)
    if not output:
        raise ValueError("At least one active scanner mode is required")
    return output


def require_entry_scope(strategy_id, *, mode, horizon=None):
    from scanner.strategy_registry import get_strategy

    definition = get_strategy(strategy_id)
    if definition.get("implementation_status") == "suspended_bearish":
        raise ValueError("Bearish strategies are paused for new scans and entries")
    if definition.get("implementation_status") == "suspended_horizon" or (
        definition.get("family") == "approved_horizon_rules"
        and (mode in PAUSED_HORIZONS or horizon in PAUSED_HORIZONS)
    ):
        raise ValueError("Intraday and short-swing scanners and new entries are paused")
