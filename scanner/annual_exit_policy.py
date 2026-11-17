"""Owner-approved annual exit policy shared by the nineteen retained rules.

Entry indicators remain native. Old ATR/headroom gates are replaced by annual
reference sizing. No evaluator in this policy can initiate a short position.
"""

from decimal import ROUND_FLOOR, Decimal

import pandas as pd

from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
from scanner.portfolio_policy import number
from scanner.vwma_yearly import INDICATORS, entry_plan

VERSION = "shared-annual-conditional-exits-v1"
REVIEW_ONLY = frozenset({"tf_medium_ema50_100", "tf_long_ema100_200"})
EXIT_ONLY = frozenset(
    {
        "tf_intraday_ema9_20_short",
        "tf_intraday_vwma9_26_short",
        "tf_intraday_vwap_breakdown_short",
        "tf_intraday_low20_breakdown_short",
        "tf_intraday_ema_adx_continuation_short",
    }
) | frozenset(k for k, setup in EMA_PIVOT_SETUPS.items() if setup.direction < 0)
AFFECTED = (
    REVIEW_ONLY
    | EXIT_ONLY
    | frozenset(
        {
            "tf_intraday_ema9_20_momentum",
            "tf_intraday_vwma9_26_rsi_volume",
            "tf_swing_ema20_50_rsi_volume",
            "tf_swing_vwma9_26_rsi_volume",
        }
    )
    | frozenset(EMA_PIVOT_SETUPS)
)
EXIT_INDICATORS = tuple(k for k in INDICATORS if not k.startswith("VWMA_"))
LEGACY_RISK_CHECKS = frozenset(
    {"positive_atr_bracket", "valid_atr_bracket", "pivot_room_at_least_1_5r"}
)


def breakout_trigger(row, tick_size):
    high, tick = number(row.get("high")), number(tick_size)
    if high is None or high <= 0 or tick is None or not 0 < tick <= 100:
        return None
    unit = Decimal(str(tick))
    return float(
        ((Decimal(str(high)) / unit).to_integral_value(rounding=ROUND_FLOOR) + 1) * unit
    )


def plan_for(strategy_id, row, *, tick_size=0.05, entry=None):
    trigger = (
        breakout_trigger(row, tick_size) if strategy_id in EMA_PIVOT_SETUPS else None
    )
    plan = entry_plan(
        row, tick_size=tick_size, entry=entry if entry is not None else trigger
    )
    if plan and trigger is not None:
        plan.update(
            entry_trigger=trigger,
            entry_order_type="NEXT_CANDLE_BREAKOUT",
            valid_for_next_candle_only=True,
        )
    return plan


def native_checks(result):
    return {
        key: value
        for key, value in result["checks"].items()
        if key not in LEGACY_RISK_CHECKS
    }


def apply_policy(strategy_id, previous, current, context, native, bearish=False):
    checks = native_checks(native)
    is_exit = strategy_id in EXIT_ONLY
    if is_exit:
        checks.pop("intraday_entry_window", None)
        checks.pop("next_entry_in_session", None)
        if strategy_id in {
            "tf_intraday_vwap_breakdown_short",
            "tf_intraday_low20_breakdown_short",
            "tf_intraday_ema_adx_continuation_short",
        }:
            stamps = [pd.Timestamp(row.name) for row in (previous, current)]
            stamps = [
                stamp.tz_localize("Asia/Kolkata")
                if stamp.tzinfo is None
                else stamp.tz_convert("Asia/Kolkata")
                for stamp in stamps
            ]
            checks["completed_intraday_pair"] = (
                context.mode == "intraday"
                and stamps[0].date() == stamps[1].date()
                and (stamps[1] - stamps[0]).total_seconds() == 900
            )
    # An old short's bearish setup now means exit; its bullish cover is ignored.
    bearish = all(checks.values()) if is_exit else bool(bearish)
    plan = (
        {} if is_exit else plan_for(strategy_id, current, tick_size=context.tick_size)
    )
    if not is_exit:
        checks["annual_targets_and_second_support_available"] = bool(plan)
    if context.mode == "intraday" and not is_exit:
        stamp = pd.Timestamp(current.name)
        stamp = (
            stamp.tz_localize("Asia/Kolkata")
            if stamp.tzinfo is None
            else stamp.tz_convert("Asia/Kolkata")
        )
        checks["next_entry_before_square_off"] = stamp.weekday() < 5 and (9, 15) <= (
            stamp.hour,
            stamp.minute,
        ) < (14, 30)
    armed = not is_exit and not bearish and all(checks.values())
    return {
        **native,
        "signal": "EXIT" if bearish else "BUY" if armed else "WAIT",
        "direction": "LONG",
        "entry_state": "EXIT_ONLY" if is_exit else "ARMED" if armed else "WAIT",
        "exit_triggered": bearish,
        "exit_only": is_exit,
        "entry_plan": plan,
        "risk": plan,
        "checks": checks,
        "passed_checks": [k for k, v in checks.items() if v],
        "failed_checks": [k for k, v in checks.items() if not v],
        "score": round(sum(checks.values()) / len(checks) * 100, 2),
        "paper_eligible": False,
        "exit_policy_version": VERSION,
        "limitations": [
            "Research only; annual conditional references are not resting "
            "stop orders or a guaranteed loss limit.",
            "Bearish setups exit existing longs only. Revised rules require "
            "new validation before automation.",
        ],
    }
