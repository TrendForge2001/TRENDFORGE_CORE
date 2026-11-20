"""Adapt approved plans to the common cost-aware paper admission policy."""

import math

from services import execution_costs
from services.approved_paper_plan import from_signal
from services.paper_admission_policy import admit, capture, fingerprint


def prepare(key, source, raw, policy):
    costs = policy["costs"][source["mode"]]
    sign = source["direction"]
    existing = source.get("execution_economics")
    if existing and math.isclose(
        raw, existing.get("entry_fill_price", -1), abs_tol=1e-8
    ):
        raw = existing["entry_raw_price"]
    price = execution_costs.fill(raw, sign, costs, opening=True)
    plan = from_signal(key, source, price)
    plan["execution_economics"] = {
        "costs": costs,
        "entry_raw_price": raw,
        "entry_fill_price": price,
        "entry_fee_per_share": execution_costs.fee(price, 1, costs),
        "admission_policy_hash": fingerprint(policy),
    }
    return plan


def economics(plan, entry):
    value = plan.get("execution_economics") if isinstance(plan, dict) else None
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "costs",
        "entry_raw_price",
        "entry_fill_price",
        "entry_fee_per_share",
        "admission_policy_hash",
    }:
        raise ValueError("Invalid paper execution-cost evidence")
    costs = execution_costs.validate(value["costs"])
    if (
        not isinstance(value["admission_policy_hash"], str)
        or len(value["admission_policy_hash"]) != 64
    ):
        raise ValueError("Invalid admission evidence")
    for name in ("entry_raw_price", "entry_fill_price", "entry_fee_per_share"):
        if (
            type(value[name]) not in (int, float)
            or not math.isfinite(value[name])
            or (value[name] < 0 if name == "entry_fee_per_share" else value[name] <= 0)
        ):
            raise ValueError("Invalid entry cost")
    expected = execution_costs.fill(
        value["entry_raw_price"], plan["direction"], costs, opening=True
    )
    if (
        not math.isclose(entry, expected, abs_tol=1e-7)
        or not math.isclose(entry, value["entry_fill_price"], abs_tol=1e-7)
        or not math.isclose(
            value["entry_fee_per_share"],
            execution_costs.fee(entry, 1, costs),
            abs_tol=1e-7,
        )
    ):
        raise ValueError("Paper fill and cost evidence disagree")
    return value


def evaluate(auto, candidate, *, now):
    key = candidate["strategy_id"]
    raw = auto._risk_metrics(candidate)["entry"]
    score, confidence = auto._score_confidence(candidate)
    policy = capture(auto)
    plan = prepare(key, candidate["paper_plan"], raw, policy)
    runtime = auto.paper_service.runtime
    positions = runtime.portfolio.positions
    symbol = str(candidate.get("symbol", "")).strip().upper()
    day = now.date().isoformat()
    limits = auto.account_entry_limits(now)
    repository = auto._repository()
    realized_fn = getattr(repository, "realized_pnl", None)
    realized = float(realized_fn()) if callable(realized_fn) else 0.0
    committed, remaining_fees, unrealized = 0.0, 0.0, 0.0
    for position in positions.values():
        qty, price = (
            auto._value(position, "quantity"),
            auto._value(position, "average_price"),
        )
        metadata = economics(auto._value(position, "paper_plan"), price)
        committed += qty * price
        remaining_fees += qty * metadata["entry_fee_per_share"] if metadata else 0.0
        unrealized += float(auto._value(position, "pnl"))
    count_fn = getattr(repository, "entries_for_date", None)
    daily_count = count_fn(day) if callable(count_fn) else 0
    state = dict(
        symbol_open=symbol in auto._open_symbols(),
        symbol_entered_today=auto._traded_today(symbol, day),
        open_positions=len(positions),
        daily_entries=daily_count,
        daily_realized_loss=auto._daily_realized_loss(day),
        daily_realized_pnl=auto._daily_realized_pnl(day),
        unrealized_pnl=unrealized,
        equity=policy["capital"] + realized + unrealized,
        realized_pnl=realized,
        committed=committed,
        open_entry_fees=remaining_fees,
    )
    result = admit(
        policy,
        plan=plan,
        score=score,
        confidence=confidence,
        now=now,
        state=state,
        allocation=candidate.get("allocated_budget"),
    )
    reasons = [*result["reasons"], *limits["reasons"]]
    if not candidate.get("execution_eligible", candidate.get("eligible", False)):
        reasons.append("scanner_not_eligible")
    if candidate.get("error"):
        reasons.append("scanner_error")
    can_open = getattr(runtime, "_can_open", None)
    if callable(can_open) and not can_open(now):
        reasons.append("outside_nse_entry_window")
    return {
        **result,
        **{name: value for name, value in limits.items() if name != "reasons"},
        "approved": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "symbol": symbol,
        "signal": "BUY" if plan["direction"] == 1 else "SELL",
        "side": "BUY" if plan["direction"] == 1 else "SHORT",
        "score": score,
        "confidence": confidence,
        "entry": plan["entry"],
        "stoploss": plan["stoploss"],
        "target2": plan.get("target2") or 0.0,
        "reward_risk": result["reward_risk"] or 0.0,
        "max_trade_value": policy["capital"]
        * policy["max_capital_per_trade_percent"]
        / 100,
        "open_positions": len(positions),
        "max_open_positions": min(3, policy["max_open_positions"]),
        "market_entry_window_open": "outside_nse_entry_window" not in reasons,
        "paper_plan": plan,
        "paper_only": True,
        "broker_orders_allowed": False,
    }
