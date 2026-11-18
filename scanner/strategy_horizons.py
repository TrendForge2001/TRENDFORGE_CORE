"""Display horizons select existing executable rules without inventing new signals."""

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.multi_strategy_engine import requires_review
from scanner.strategy_registry import SCANNER_CHOICE_IDS, list_strategies
from scanner.technical_strategy import strategy_profile
from scanner.weekly_floor import STRATEGY_ID as WEEKLY_FLOOR_ID

HORIZONS = {
    "intraday": "Intraday",
    "short_swing": "Short Swing",
    "short_term": "Short Term",
    "medium_term": "Medium Term",
    "long_term": "Long Term",
}


def horizon_strategies(horizon: str) -> dict[str, dict]:
    if horizon not in HORIZONS:
        raise ValueError("Unknown trading horizon")
    mode = (
        "intraday"
        if horizon == "intraday"
        else "positional"
        if horizon == "long_term"
        else "swing"
    )
    choices = {}
    for row in list_strategies(mode=mode):
        strategy_id = row["strategy_id"]
        from scanner.approved_strategies import active, horizons

        if requires_review(strategy_id):
            continue
        if active(strategy_id):
            if horizon not in horizons(strategy_id):
                continue
            profile = strategy_profile(mode)
            borrow = mode == "intraday" and row.get("direction") == "SHORT"
            choices[
                row["name"]
                + " · "
                + HORIZONS[horizon]
                + (" · paper short availability assumed" if borrow else "")
            ] = dict(
                horizon=horizon,
                strategy_id=strategy_id,
                mode=mode,
                interval=profile.interval,
                period=profile.default_period,
                short_borrow_available=borrow,
            )
            continue
        setup = EMA_PIVOT_SETUPS.get(strategy_id)
        if horizon == "short_swing" and (setup is None or setup.fast != 9):
            continue
        if horizon == "short_term" and setup is not None and setup.fast != 20:
            continue
        if horizon == "medium_term" and (setup is None or setup.fast != 50):
            continue
        weekly = strategy_id == WEEKLY_FLOOR_ID
        if (
            horizon == "long_term"
            and not weekly
            and (setup is None or setup.fast != 100)
        ):
            continue
        borrow = row.get("direction") == "SHORT"
        label = row["name"] + (" · borrow assumed" if borrow else "")
        profile = strategy_profile(mode)
        choices[label] = {
            "horizon": horizon,
            "strategy_id": strategy_id,
            "mode": mode,
            "interval": "1wk" if weekly else profile.interval,
            "period": profile.default_period,
            "short_borrow_available": borrow,
        }
    return dict(
        sorted(
            choices.items(), key=lambda item: item[1]["strategy_id"] != WEEKLY_FLOOR_ID
        )
    )


def horizon_strategy(horizon: str, strategy_id: str, period: str | None = None) -> dict:
    for row in horizon_strategies(horizon).values():
        if row["strategy_id"] == strategy_id:
            if period is not None:
                if period not in strategy_profile(row["mode"]).allowed_periods:
                    raise ValueError(
                        "Backtesting period is unavailable for this horizon"
                    )
                row = {**row, "period": period}
            return row
    raise ValueError("Strategy is unavailable for this trading horizon")


def scanner_horizon_choices(horizon):
    return {
        label: row
        for label, row in horizon_strategies(horizon).items()
        if row["strategy_id"] in SCANNER_CHOICE_IDS
    }
