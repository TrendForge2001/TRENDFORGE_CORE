"""Bounded backtest summaries for an explicitly requested private operator review.

Only registered strategy identifiers and allowlisted aggregate numbers leave the
saved snapshot. No symbols, trades, account details, errors or credentials do.
These are independent per-symbol simulations, never a combined portfolio.
"""

import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing

from core.storage_config import resolve_storage
from scanner.strategy_registry import REGISTRY_VERSION, get_strategy
from services.validation_journal import decode_rows

NUMBERS = (
    "completed_symbols",
    "error_symbols",
    "coverage_pct",
    "total_trades",
    "net_pnl",
    "transaction_costs",
    "slippage_impact_estimate",
    "profit_factor",
    "trade_win_rate_pct",
    "average_max_drawdown_pct",
    "worst_max_drawdown_pct",
    "median_symbol_return_pct",
    "profitable_symbol_pct",
    "independent_capital_per_symbol",
    "aggregate_test_capital",
    "return_on_aggregate_test_capital_pct",
    "loss_making_symbols",
    "flat_traded_symbols",
    "no_trade_symbols",
    "active_profitable_symbol_pct",
    "active_median_symbol_return_pct",
)
CHECKS = (
    "minimum_completed_symbols",
    "minimum_total_trades",
    "minimum_universe_scope",
    "coverage",
    "positive_net_pnl",
    "profitable_symbol_pct",
    "profit_factor",
    "median_symbol_return",
    "average_drawdown",
    "worst_drawdown",
)


def error_diagnostics(validation):
    """Read existing journal errors without publishing their free-form text."""
    run = validation.get("run_id")
    if not isinstance(run, str) or not run:
        return {"status": "unavailable"}
    path = (
        resolve_storage().database.resolve().parent
        / "validation"
        / (hashlib.sha256(run.encode()).hexdigest() + ".sqlite")
    )
    counts = Counter()
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            metadata = json.loads(
                connection.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0]
            )
            if metadata.get("registry_version") != REGISTRY_VERSION or metadata.get(
                "request"
            ) != validation.get("request"):
                return {"status": "unavailable"}
            for (payload,) in connection.execute("SELECT errors FROM units"):
                for error in decode_rows(payload):
                    text = str(error.get("error") or "").lower()
                    mode, phase = error.get("mode"), error.get("phase")
                    mode = (
                        mode
                        if mode in {"intraday", "swing", "positional"}
                        else "unknown"
                    )
                    phase = (
                        phase
                        if phase in {"backtest", "market_data", "indicator_pipeline"}
                        else "unknown"
                    )
                    cause = "unclassified"
                    if "missing its 15:00 ist square-off candle" in text:
                        cause = "missing_1500_square_off_candle"
                    elif "candle interval mismatch" in text:
                        cause = "candle_interval_mismatch"
                    elif (
                        "at least 120 completed candles" in text
                        or "insufficient completed history" in text
                    ):
                        cause = "insufficient_completed_history"
                    elif "intraday paper short availability" in text:
                        cause = "short_availability_not_assumed"
                    elif (
                        "tokenexception" in text
                        or "authentication" in text
                        or "invalid token" in text
                    ):
                        cause = "authentication_failure"
                    elif "too many requests" in text or "rate limit" in text:
                        cause = "provider_rate_limit"
                    elif text.startswith("keyerror:"):
                        cause = "missing_indicator_or_field"
                    elif "tz-naive" in text or "tz-aware" in text:
                        cause = "timezone_mismatch"
                    counts[(mode, phase, cause)] += 1
    except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
        return {"status": "unavailable"}
    return {
        "status": "available",
        "total_errors": sum(counts.values()),
        "counts": [
            dict(mode=mode, phase=phase, cause=cause, count=count)
            for (mode, phase, cause), count in sorted(counts.items())
        ],
    }


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return value


def validation_review(validation, universe):
    if (
        validation.get("status") != "completed"
        or validation.get("registry_version") != REGISTRY_VERSION
        or validation.get("output_exists") is not True
        or universe not in {"NIFTY 100", "NIFTY 200", "NIFTY 500"}
    ):
        raise ValueError("A saved current-registry result is required")
    source = validation.get("strategy_universe_metrics")
    if not isinstance(source, list) or len(source) > 1000:
        raise ValueError("Bounded strategy metrics required")
    rows, seen = [], set()
    for item in source:
        if not isinstance(item, dict) or item.get("universe") != universe:
            continue
        key, mode = item.get("strategy_id"), item.get("mode")
        if not isinstance(key, str) or mode not in {"intraday", "swing", "positional"}:
            continue
        try:
            key = get_strategy(key)["strategy_id"]
        except (KeyError, ValueError):
            continue
        if (key, mode) in seen:
            raise ValueError("Duplicate strategy metrics")
        seen.add((key, mode))
        gate = item.get("validation_gate")
        gate = gate if isinstance(gate, dict) else {}
        checks = gate.get("checks")
        checks = checks if isinstance(checks, dict) else {}
        row = {
            "universe": universe,
            "strategy_id": key,
            "mode": mode,
            **{name: _number(item.get(name)) for name in NUMBERS},
            "gate": gate.get("status")
            if gate.get("status") in {"PASS", "FAIL", "INSUFFICIENT_DATA"}
            else "unknown",
            "registry_paper_eligible": item.get("registry_paper_eligible") is True,
            "failed_checks": [name for name in CHECKS if checks.get(name) is False],
        }
        allowed_rejections = {
            "signal_not_allowed",
            "score_below_minimum",
            "confidence_below_minimum",
            "stoploss_invalid",
            "reward_risk_below_minimum",
            "position_already_open",
            "symbol_already_traded_today",
            "maximum_open_positions_reached",
            "maximum_daily_entries_reached",
            "maximum_daily_loss_reached",
            "outside_nse_entry_window",
            "two_shares_required_for_partial_exit",
            "position_size_zero",
            "target_does_not_cover_modeled_costs",
            "maximum_entries_per_scan_reached",
            "observed_0930_execution_session_unavailable",
            "short_availability_not_assumed",
            "scanner_consensus_conflict",
            "actual_fill_failed_reference_or_target_ordering",
            "next_native_open_unavailable",
            "insufficient_reference_risk_or_cash_budget",
            "cash_budget_exceeded",
        }
        row["admission_rejection_counts"] = {
            key: value
            for key, value in (item.get("admission_rejection_counts") or {}).items()
            if key in allowed_rejections and type(value) is int and value >= 0
        }
        net, costs = row["net_pnl"], row["transaction_costs"]
        row["gross_pnl_before_transaction_costs"] = (
            round(net + costs, 2) if net is not None and costs is not None else None
        )
        rows.append(row)
    return {
        "universe": universe,
        "currency": "INR",
        "registry_version": REGISTRY_VERSION,
        "master_symbol_count": _number(validation.get("master_symbol_count")),
        "error_count": _number(validation.get("error_count")),
        "strategy_mode_count": len(rows),
        "passed": sum(row["gate"] == "PASS" for row in rows),
        "failed": sum(row["gate"] == "FAIL" for row in rows),
        "insufficient": sum(row["gate"] == "INSUFFICIENT_DATA" for row in rows),
        "capital_basis": "independent_per_symbol_not_a_shared_portfolio",
        "gross_basis": "net_plus_transaction_costs_slippage_already_in_fills",
        "rows": rows,
    }
