"""Versioned, explicitly modeled costs shared by historical and paper fills.

This is a research estimator, not a broker contract note or a point-in-time
historical tax schedule. Slippage changes fills; it is never deducted twice.
"""

import math

VERSION = "percentage-fees-dp-estimate-2026-11-v1"
MODES = ("intraday", "swing", "positional")


def model(mode):
    if mode not in MODES:
        raise ValueError("Unknown execution mode")
    return {
        "version": VERSION,
        "fee_bps": 4.0 if mode == "intraday" else 12.0,
        "slippage_bps": 5.0,
        "overnight_delivery_exit_charge": 0.0 if mode == "intraday" else 15.34,
        "historical_fee_schedule": False,
    }


def validate(value):
    if not isinstance(value, dict) or set(value) != set(model("intraday")):
        raise ValueError("Explicit versioned execution-cost model required")
    if value["version"] != VERSION or value["historical_fee_schedule"] is not False:
        raise ValueError("Unsupported execution-cost basis")
    for key, maximum in (
        ("fee_bps", 1000),
        ("slippage_bps", 1000),
        ("overnight_delivery_exit_charge", 1000),
    ):
        number = value[key]
        if (
            type(number) not in (int, float)
            or not math.isfinite(number)
            or not 0 <= number <= maximum
        ):
            raise ValueError("Invalid modeled execution cost")
    return dict(value)


def fill(raw, sign, costs, *, opening=False, limit=None):
    raw = float(raw)
    if not math.isfinite(raw) or raw <= 0 or sign not in (-1, 1):
        raise ValueError("Invalid modeled fill")
    price = raw * (1 + (sign if opening else -sign) * costs["slippage_bps"] / 10000)
    if limit is not None:
        price = max(price, limit) if sign > 0 else min(price, limit)
    return price


def fee(price, quantity, costs):
    return price * quantity * costs["fee_bps"] / 10000


def viable_target(entry, target, sign, quantity, costs, *, delivery=False):
    if target is None:
        return True  # an indicator trail has no promised fixed target
    gross = sign * (target - entry) * quantity
    charges = fee(entry, quantity, costs) + fee(target, quantity, costs)
    if delivery:
        charges += costs["overnight_delivery_exit_charge"]
    return gross > charges


def exit_economics(
    entry,
    raw_exit,
    quantity,
    sign,
    costs,
    *,
    entry_raw=None,
    limit=None,
    delivery_charge=0,
):
    price = fill(raw_exit, sign, costs, limit=limit)
    charges = (
        fee(entry, quantity, costs) + fee(price, quantity, costs) + delivery_charge
    )
    gross = sign * (price - entry) * quantity
    return {
        "exit_price": price,
        "gross_pnl": gross,
        "transaction_costs": charges,
        "net_pnl": gross - charges,
        "slippage_impact_estimate": sign
        * (
            (entry - (entry_raw if entry_raw is not None else entry))
            + (raw_exit - price)
        )
        * quantity,
        "cost_model_version": VERSION,
        "delivery_charge": delivery_charge,
    }
