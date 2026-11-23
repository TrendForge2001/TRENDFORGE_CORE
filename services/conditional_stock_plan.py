"""Non-executing price plans for stocks without a complete scanner setup."""

import math


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def conditional_plan(candles, *, horizon):
    base = {
        "status": "CONDITIONAL_REFERENCE",
        "basis": "20-session high/low with 0.1% buffers; projected 2R",
        "execution_enabled": False,
        "reviewable_setup": False,
        "stop_is_resting_order": False,
        "targets": [],
        "entry": None,
        "stop_reference": None,
        "entry_order_type": "Completed daily breakout confirmation; not an order",
        "conditions_text": [
            "Wait for a completed daily close above the entry trigger.",
            "Confirm RSI14 above 50 and volume above its 20-session simple average.",
            "Confirm EMA20 above EMA50."
            if horizon == "short_term"
            else "Confirm EMA100 above EMA200 before considering entry.",
            "Recheck the current quote, risk and approved strategy "
            "before any paper entry.",
        ],
    }
    if len(candles) < 20:
        return {
            **base,
            "status": "DATA_UNAVAILABLE",
            "reason": (
                "At least 20 completed daily candles are required for reference prices."
            ),
        }
    rows = [
        {key: number(row.get(key)) for key in ("low", "high", "close")}
        for row in candles[-20:]
    ]
    if not all(
        all(row[key] is not None and row[key] > 0 for key in ("low", "high", "close"))
        and row["low"] <= row["close"] <= row["high"]
        for row in rows
    ):
        return {
            **base,
            "status": "DATA_UNAVAILABLE",
            "reason": "Valid daily price evidence is unavailable.",
        }
    high, low = max(row["high"] for row in rows), min(row["low"] for row in rows)
    # An explicit 0.1% planning buffer avoids treating an exact touch as a break.
    entry = round(high * 1.001, 2)
    stop = round(low * 0.999, 2)
    if not 0 < stop < entry:
        return {
            **base,
            "status": "DATA_UNAVAILABLE",
            "reason": "Reference risk is invalid.",
        }
    target = round(entry + 2 * (entry - stop), 2)
    if number(target) is None or target <= entry:
        return {
            **base,
            "status": "DATA_UNAVAILABLE",
            "reason": "Reference target is invalid.",
        }
    return {
        **base,
        "entry": entry,
        "stop_reference": stop,
        "targets": [target],
        "reference_date": candles[-1]["date"],
        "lookback_sessions": 20,
        "lookback_high": high,
        "lookback_low": low,
        "risk_per_share": round(entry - stop, 2),
        "exit_condition": (
            "Planning profit exit at the 2R target; reassess "
            "on a daily close below the support reference."
        ),
        "reason": (
            "Independent conditional reference, available even "
            "without a scanner match. "
            "The 2R target is a risk projection, not a price forecast "
            "or an approved strategy target. "
            "Your selected strategy's approved exits still govern "
            "any position opened under it."
        ),
    }


def display_plan(report):
    approved = report.get("trade_plan") or {}
    entry, stop = number(approved.get("entry")), number(approved.get("stop_reference"))
    targets = [number(value) for value in approved.get("targets", [])]
    if entry and stop and 0 < stop < entry and any(v and v > entry for v in targets):
        return approved
    return report.get("conditional_plan") or approved
