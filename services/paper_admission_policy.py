"""Pure, frozen account admission shared by approved paper and historical paths."""

import hashlib
import json
import math
from datetime import time

from services import execution_costs
from services.market_day_service import MarketDayService
from services.trading_calendar import (
    calendar_arguments,
    configured_calendar,
    normalize_calendar,
)

VERSION = "approved-paper-admission-v3-calendar"
FIELDS = (
    "capital",
    "cash_reserve",
    "max_deployed_capital",
    "max_daily_entries",
    "staged_risk_percent",
    "daily_loss_basis",
    "risk_per_trade_percent",
    "max_daily_loss_percent",
    "max_open_positions",
    "max_capital_per_trade_percent",
    "minimum_rr",
    "minimum_score",
    "minimum_confidence",
    "max_entries_per_scan",
    "allowed_signals",
)


def capture(auto):
    value = {name: getattr(auto, name) for name in FIELDS}
    value["allowed_signals"] = list(value["allowed_signals"])
    value.update(
        version=VERSION,
        costs={mode: execution_costs.model(mode) for mode in execution_costs.MODES},
        calendar=configured_calendar(),
    )
    return validate(value)


def validate(value):
    if (
        not isinstance(value, dict)
        or set(value) != {*FIELDS, "version", "costs", "calendar"}
        or value.get("version") != VERSION
    ):
        raise ValueError("A frozen saved paper-admission policy is required")
    limits = {
        "capital": (1000, 1e9),
        "cash_reserve": (0, 1e9),
        "max_deployed_capital": (0, 1e9),
        "max_daily_entries": (0, 100),
        "staged_risk_percent": (0.1, 0.5),
        "risk_per_trade_percent": (0.1, 5),
        "max_daily_loss_percent": (0.1, 20),
        "max_open_positions": (1, 25),
        "max_capital_per_trade_percent": (1, 100),
        "minimum_rr": (1, 10),
        "minimum_score": (0, 100),
        "minimum_confidence": (0, 100),
        "max_entries_per_scan": (1, 10),
    }
    for name, (low, high) in limits.items():
        number = value[name]
        if (
            type(number) not in (int, float)
            or not math.isfinite(number)
            or not low <= number <= high
        ):
            raise ValueError("Invalid saved admission policy")
    for name in ("max_daily_entries", "max_open_positions", "max_entries_per_scan"):
        if type(value[name]) is not int:
            raise ValueError("Integer account limit required")
    if (
        abs(value["cash_reserve"] + value["max_deployed_capital"] - value["capital"])
        > 1e-6
    ):
        raise ValueError("Inconsistent account cash limits")
    if value["daily_loss_basis"] not in {"realized_losses", "realized_plus_unrealized"}:
        raise ValueError("Unknown saved loss policy")
    if (
        not isinstance(value["allowed_signals"], list)
        or not value["allowed_signals"]
        or any(
            s
            not in {
                "BUY",
                "STRONG BUY",
                "STRONG_BUY",
                "SELL",
                "STRONG SELL",
                "STRONG_SELL",
            }
            for s in value["allowed_signals"]
        )
    ):
        raise ValueError("Invalid saved signal policy")
    if not isinstance(value["costs"], dict) or set(value["costs"]) != set(
        execution_costs.MODES
    ):
        raise ValueError("Explicit costs for every horizon required")
    for costs in value["costs"].values():
        execution_costs.validate(costs)
    normalize_calendar(value["calendar"])
    return json.loads(json.dumps(value, allow_nan=False))


def fingerprint(policy):
    return hashlib.sha256(
        json.dumps(validate(policy), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def admit(policy, *, plan, score, confidence, now, state, allocation=None):
    """No environment, broker, database or discretionary strategy decisions."""
    now = MarketDayService.local_now(now)
    costs, entry, stop = policy["costs"][plan["mode"]], plan["entry"], plan["stoploss"]
    sign = plan["direction"]
    target = plan.get("target2")
    risk = sign * (entry - stop)
    reasons = []
    numeric_state = (
        "open_positions",
        "daily_entries",
        "daily_realized_loss",
        "daily_realized_pnl",
        "unrealized_pnl",
        "equity",
        "realized_pnl",
        "committed",
    )
    if any(
        type(state.get(key)) not in (int, float) or not math.isfinite(state[key])
        for key in numeric_state
    ):
        raise ValueError("Finite account state is required")
    if any(
        state[key] < 0
        for key in (
            "open_positions",
            "daily_entries",
            "daily_realized_loss",
            "committed",
        )
    ):
        raise ValueError("Account counts and collateral cannot be negative")
    if (
        not all(math.isfinite(float(v)) for v in (score, confidence, entry, stop))
        or entry <= 0
    ):
        raise ValueError("Finite candidate evidence is required")
    signal = "BUY" if sign == 1 else "SELL"
    if signal not in policy["allowed_signals"]:
        reasons.append("signal_not_allowed")
    if score < policy["minimum_score"]:
        reasons.append("score_below_minimum")
    if confidence < policy["minimum_confidence"]:
        reasons.append("confidence_below_minimum")
    reward_risk = (
        sign * (target - entry) / risk if target is not None and risk > 0 else None
    )
    if risk <= 0:
        reasons.append("stoploss_invalid")
    elif reward_risk is not None and reward_risk + 1e-6 < policy["minimum_rr"]:
        reasons.append("reward_risk_below_minimum")
    if state.get("symbol_open"):
        reasons.append("position_already_open")
    if state.get("symbol_entered_today"):
        reasons.append("symbol_already_traded_today")
    if state["open_positions"] >= min(3, policy["max_open_positions"]):
        reasons.append("maximum_open_positions_reached")
    if (
        policy["max_daily_entries"]
        and state["daily_entries"] >= policy["max_daily_entries"]
    ):
        reasons.append("maximum_daily_entries_reached")
    loss = state["daily_realized_loss"]
    if policy["daily_loss_basis"] == "realized_plus_unrealized":
        loss = max(loss, -state["daily_realized_pnl"] - state["unrealized_pnl"])
    if loss >= policy["capital"] * policy["max_daily_loss_percent"] / 100:
        reasons.append("maximum_daily_loss_reached")
    if not MarketDayService.is_session_date(
        now.date(), **calendar_arguments(policy["calendar"])
    ) or not time(9, 30) <= now.time().replace(tzinfo=None) < time(14, 45):
        reasons.append("outside_nse_entry_window")
    risk_budget = (
        max(0, state["equity"])
        * min(policy["staged_risk_percent"], policy["risk_per_trade_percent"])
        / 100
    )
    initial_budget = policy["capital"] * policy["risk_per_trade_percent"] / 100
    available = max(
        0,
        min(
            policy["max_deployed_capital"],
            policy["capital"] + state["realized_pnl"] - policy["cash_reserve"],
        )
        - state["committed"]
        - state.get("open_entry_fees", 0),
    )
    budget = min(
        available,
        policy["capital"] * policy["max_capital_per_trade_percent"] / 100,
        allocation if allocation is not None else available,
    )
    reference_fill = execution_costs.fill(stop, sign, costs)
    reference_cost = sign * (entry - reference_fill) + execution_costs.fee(
        entry + reference_fill, 1, costs
    )
    fixed_risk_cost = (
        costs["overnight_delivery_exit_charge"] if plan["mode"] != "intraday" else 0.0
    )
    quantity = (
        max(
            0,
            min(
                math.floor(budget / (entry + execution_costs.fee(entry, 1, costs))),
                math.floor(
                    max(0, min(initial_budget, risk_budget) - fixed_risk_cost)
                    / reference_cost
                ),
            ),
        )
        if entry > 0 and reference_cost > 0
        else 0
    )
    if quantity < (2 if plan.get("annual") else 1):
        reasons.append(
            "two_shares_required_for_partial_exit"
            if plan.get("annual")
            else "position_size_zero"
        )
    targets = [(target, quantity)] if target is not None else []
    if plan.get("annual"):
        targets = [
            (plan["partial_target"], quantity // 2),
            (target, quantity - quantity // 2),
        ]
    if quantity and any(
        not execution_costs.viable_target(
            entry, level, sign, leg_quantity, costs, delivery=plan["mode"] != "intraday"
        )
        for level, leg_quantity in targets
    ):
        reasons.append("target_does_not_cover_modeled_costs")
    return {
        "approved": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "quantity": quantity,
        "reward_risk": reward_risk,
        "risk_budget": risk_budget,
        "remaining_entry_capital": available,
        "policy_hash": fingerprint(policy),
        "planned_initial_risk": quantity * reference_cost + fixed_risk_cost,
    }
