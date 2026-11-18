"""Bounded backtest summaries for an explicitly requested private operator review.

Only registered strategy identifiers and allowlisted aggregate numbers leave the
saved snapshot. No symbols, trades, account details, errors or credentials do.
These are independent per-symbol simulations, never a combined portfolio.
"""

import math

from scanner.strategy_registry import REGISTRY_VERSION, get_strategy

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
