"""Independent arithmetic checks over saved paper fills; never repairs a ledger."""

import math

from services.execution_costs import VERSION, validate
from services.strategy_provenance import identity, plan_from

EXIT_REASONS = {
    "STOPLOSS": "The observed quote was at or beyond the price-triggered stop.",
    "TARGET": "The observed quote reached the recorded profit target.",
    "PARTIAL_PROFIT": (
        "A partial profit exit was recorded; the remainder is a separate position."
    ),
    "R3_FINAL_TARGET": "The final yearly R3 target was reached.",
    "R2_CLOSE_CONFIRMED_PROFIT": (
        "The approved R2 candle-confirmation profit condition completed."
    ),
    "EMA50_TWO_DAILY_CLOSES_STOP": (
        "Two completed post-entry daily candles closed below EMA50."
    ),
    "EMA20_TRAILING_EXIT": (
        "A completed candle closed below the approved EMA20 profit trail."
    ),
    "EMA50_TRAILING_EXIT": (
        "A completed candle closed below the approved EMA50 profit trail."
    ),
    "VWMA26_CONFIRMED_STOP": (
        "The VWMA26 stop condition completed with the required RSI "
        "and volume confirmation."
    ),
    "VWMA9_CONFIRMED_EXIT": (
        "The VWMA9 exit condition completed with the required RSI and"
        " volume confirmation."
    ),
    "SELLING_VOLUME_SUPPORT_EXIT": (
        "The selling-volume and support-break rule group completed."
    ),
    "RSI_GAP_OPEN_EXIT": "The approved RSI and opening-gap exit group completed.",
    "RSI_GAP_CLOSE_CONFIRMED_EXIT": (
        "The approved RSI and gap-down candle exit group completed."
    ),
    "BEARISH_SETUP_EXIT": (
        "An approved bearish setup closed the existing long position."
    ),
    "PIVOT_CONFIRMED_STOP": (
        "A completed candle violated the approved pivot support reference."
    ),
    "PIVOT_OR_EMA50_CONFIRMED_STOP": (
        "A completed candle violated pivot support or EMA50."
    ),
    "FORCE_EXIT_15_00_IST": "The intraday square-off time was reached.",
    "MISSED_INTRADAY_SQUARE_OFF": (
        "A carried intraday position was closed after its square-off was missed."
    ),
    "STRATEGY_EXIT": "The saved strategy exit signal requested closure.",
}


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def audit(row):
    plan = plan_from(row)
    fill_reason = row.get("exit_reason")
    reason = (
        row.get("exit_signal")
        if fill_reason == "STRATEGY_EXIT" and row.get("exit_signal")
        else fill_reason or row.get("exit_signal")
    )
    reason = reason if isinstance(reason, str) and reason.strip() else None
    explanation = EXIT_REASONS.get(reason) if reason else None
    if not explanation:
        explanation = (
            (
                "A recorded strategy/operator exit closed this fill; see its "
                "saved exit code."
            )
            if reason
            else "The historical fill has no recorded exit reason."
        )
    result = {
        "version": "paper-fill-audit-v1",
        "status": "LIMITED_EVIDENCE",
        "accounting_status": "LIMITED_EVIDENCE",
        "strategy": identity(row, plan=plan),
        "recorded_exit_reason": fill_reason,
        "exit_code": reason,
        "exit_explanation": explanation,
        "exit_signal_at": row.get("exit_signal_at"),
        "closed_at": row.get("closed_at"),
        "stop_basis": "conditional_reference"
        if plan.get("stop_is_resting_order") is False
        else "price_trigger"
        if plan.get("stop_is_resting_order") is True
        else "unrecorded",
        "checks": {},
        "missing": [],
        "failures": [],
        "formula": (
            "Gross = direction × (exit fill − entry fill) × quantity; net"
            " = gross − recorded charges. Slippage is already in the "
            "fills."
        ),
    }
    checks, missing = result["checks"], result["missing"]
    if not row.get("closed_at"):
        missing.append("exit_timestamp")
    if not row.get("cost_model_version"):
        missing.append("fee_and_slippage_basis")
    if fill_reason == "STRATEGY_EXIT" and not row.get("exit_signal_at"):
        missing.append("exit_signal_timestamp")
    if not reason:
        missing.append("exit_reason")
    elif reason not in EXIT_REASONS:
        missing.append("exit_rule_description")
    for key in ("strategy_id", "registry_version", "policy_version"):
        if result["strategy"][key] == "unrecorded":
            missing.append(key)
    qty, entry, exit_price, recorded = (
        numeric(row.get(k)) for k in ("quantity", "entry_price", "exit_price", "pnl")
    )
    side = str(row.get("side") or "").upper()
    if (
        None in (qty, entry, exit_price, recorded)
        or qty <= 0
        or not qty.is_integer()
        or min(entry, exit_price) <= 0
        or side not in {"BUY", "LONG", "SELL", "SHORT"}
    ):
        result.update(
            status="INVALID_EVIDENCE",
            accounting_status="INVALID_EVIDENCE",
            failures=["Invalid quantity, direction, fill or P&L evidence"],
        )
        return result
    sign = -1 if side in {"SELL", "SHORT"} else 1
    gross = sign * (exit_price - entry) * qty
    costs = numeric(row.get("transaction_costs"))
    result.update(
        entry_fill=entry,
        exit_fill=exit_price,
        quantity=qty,
        computed_gross_pnl=gross,
        recorded_net_pnl=recorded,
        recorded_charges=costs,
    )

    def check(name, actual, expected, *, tolerance=0.01):
        actual = numeric(actual)
        checks[name] = actual is not None and abs(actual - expected) <= tolerance

    if costs is not None and costs >= 0:
        check("gross_pnl", row.get("gross_pnl"), gross)
        check("net_pnl", recorded, gross - costs)
        result["computed_net_pnl"] = gross - costs
    elif costs is not None or row.get("cost_model_version"):
        checks["charges"] = False
    else:
        check("legacy_gross_pnl", recorded, gross)
    source = plan.get("execution_economics")
    source = source if isinstance(source, dict) else {}
    if row.get("cost_model_version") == VERSION and source:
        try:
            model = validate(source.get("costs"))
            raw_entry = numeric(source.get("entry_raw_price"))
            raw_exit = numeric(row.get("exit_raw_price"))
            delivery = numeric(row.get("delivery_charge"))
            if None in (raw_entry, raw_exit, delivery) or min(raw_entry, raw_exit) <= 0:
                raise ValueError("Missing saved cost inputs")
            check(
                "entry_fill",
                entry,
                raw_entry * (1 + sign * model["slippage_bps"] / 10000),
                tolerance=1e-7,
            )
            expected_exit = raw_exit * (1 - sign * model["slippage_bps"] / 10000)
            limit = (
                plan.get("partial_target")
                if fill_reason == "PARTIAL_PROFIT"
                else plan.get("target2")
                if fill_reason in {"TARGET", "R3_FINAL_TARGET"}
                else None
            )
            if limit is not None:
                limit = numeric(limit)
                if limit is None or limit <= 0:
                    raise ValueError("Invalid saved limit")
                expected_exit = (
                    max(expected_exit, limit) if sign > 0 else min(expected_exit, limit)
                )
            check("exit_fill", exit_price, expected_exit, tolerance=1e-7)
            checks["delivery_charge"] = delivery in {
                0.0,
                model["overnight_delivery_exit_charge"],
            }
            check(
                "transaction_costs",
                costs,
                (entry + exit_price) * qty * model["fee_bps"] / 10000 + delivery,
            )
            check(
                "slippage_impact",
                row.get("slippage_impact_estimate"),
                sign * ((entry - raw_entry) + (raw_exit - exit_price)) * qty,
            )
            result.update(
                raw_entry_price=raw_entry,
                raw_exit_price=raw_exit,
                slippage_bps=model["slippage_bps"],
                delivery_charge=delivery,
            )
        except (TypeError, ValueError, KeyError):
            missing.append("valid_saved_execution_cost_inputs")
    elif row.get("cost_model_version"):
        missing.append("supported_saved_cost_model")
    stop = numeric(row.get("stoploss"))
    if stop is not None and stop > 0:
        result["adverse_distance_from_stop"] = max(0.0, sign * (stop - exit_price))
        result["stop_note"] = (
            "Conditional references wait for approved indicator/candle confirmation. "
            "A trigger price does not guarantee the fill price; observed "
            "quotes and modeled slippage determine the fill."
        )
    result["failures"] = [key for key, passed in checks.items() if not passed]
    financial_missing = {
        "fee_and_slippage_basis",
        "valid_saved_execution_cost_inputs",
        "supported_saved_cost_model",
    }
    result["accounting_status"] = (
        "MISMATCH"
        if result["failures"]
        else "LIMITED_EVIDENCE"
        if financial_missing.intersection(missing)
        else "VERIFIED"
    )
    result["status"] = (
        "MISMATCH"
        if result["failures"]
        else "LIMITED_EVIDENCE"
        if missing
        else "VERIFIED"
    )
    return result
