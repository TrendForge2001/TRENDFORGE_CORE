"""Read-only, bounded economic diagnostics from private validation checkpoints.

Only registered strategy identifiers, fixed exit reasons and aggregate numbers
leave this module. It cannot change performance gates or trading controls.
"""

import hashlib
import json
import math
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

from core.storage_config import resolve_storage
from scanner.approved_strategies import APPROVED_IDS
from scanner.strategy_registry import REGISTRY_VERSION

EXITS = frozenset(
    [
        "INTRADAY_SQUARE_OFF",
        "RSI_GAP_OPEN_EXIT",
        "STOPLOSS",
        "R1_PARTIAL_PROFIT",
        "R3_FINAL_TARGET",
        "STRATEGY_TARGET",
        "END_OF_TEST",
        "RSI_GAP_CLOSE_CONFIRMED_EXIT",
        "SELLING_VOLUME_SUPPORT_EXIT",
        "BEARISH_SETUP_EXIT",
        "R2_CLOSE_CONFIRMED_PROFIT",
        "EMA9_20_REVERSAL_EXIT",
        "VWMA26_CONFIRMED_STOP",
        "VWMA9_26_CONFIRMED_EXIT",
        "EMA50_TWO_DAILY_CLOSES_STOP",
        "VWMA9_CONFIRMED_EXIT",
        "VWAP_RECLAIM_EXIT",
        "EMA20_CONFIRMED_STOP",
        "ADX_BELOW20_EXIT",
        "PIVOT_OR_EMA50_CONFIRMED_STOP",
        "PIVOT_CONFIRMED_STOP",
        "EMA100_CONFIRMED_STOP",
        "EMA200_CONFIRMED_STOP",
        "EMA20_TRAILING_EXIT",
        "EMA50_TRAILING_EXIT",
    ]
)
IST = ZoneInfo("Asia/Kolkata")


def _number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else 0.0


def _stamp(value):
    stamp = datetime.fromisoformat(value)
    return stamp.replace(tzinfo=IST) if stamp.tzinfo is None else stamp.astimezone(IST)


def _mean(total, count):
    return round(total / count, 4) if count else None


def trade_diagnostics(validation, universe):
    """Stream one stock/mode unit at a time; never load the full report or trades."""
    if (
        validation.get("status") != "completed"
        or validation.get("registry_version") != REGISTRY_VERSION
        or universe not in {"NIFTY 100", "NIFTY 200", "NIFTY 500"}
        or not isinstance(validation.get("run_id"), str)
        or not validation["run_id"]
    ):
        return {"status": "unavailable", "rows": []}
    path = (
        resolve_storage().database.resolve().parent
        / "validation"
        / (hashlib.sha256(validation["run_id"].encode()).hexdigest() + ".sqlite")
    )
    groups = {}
    try:
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        ) as connection:
            connection.execute("PRAGMA query_only=ON")
            metadata = json.loads(
                connection.execute("SELECT payload FROM meta WHERE id=1").fetchone()[0]
            )
            if any(
                metadata.get(key) != validation.get(key)
                for key in ("run_id", "request", "registry_version")
            ):
                return {"status": "unavailable", "rows": []}
            for tests_json, trades_json in connection.execute(
                "SELECT backtests, trades FROM units ORDER BY rowid"
            ):
                tests, trades = json.loads(tests_json), json.loads(trades_json)
                for test in tests:
                    key, mode = test.get("strategy_id"), test.get("mode")
                    if (
                        key not in APPROVED_IDS
                        or mode not in {"intraday", "swing", "positional"}
                        or test.get("status") != "completed"
                        or test.get("membership", {}).get(universe) is not True
                    ):
                        continue
                    group = groups.setdefault(
                        (key, mode),
                        {
                            "counts": Counter(),
                            "exits": {},
                            "active_returns": [],
                            "sums": Counter(),
                            "dates": [],
                            "first_trade": None,
                            "last_trade": None,
                        },
                    )
                    counts, sums = group["counts"], group["sums"]
                    counts["completed_symbols"] += 1
                    net = _number(test.get("net_profit"))
                    counts[
                        "profitable_symbols"
                        if net > 0
                        else "losing_symbols"
                        if net < 0
                        else "flat_symbols"
                    ] += 1
                    active = _number(test.get("total_trades")) > 0
                    counts["traded_symbols" if active else "no_trade_symbols"] += 1
                    result = _number(test.get("return_pct"))
                    if active:
                        group["active_returns"].append(result)
                        counts["profitable_traded_symbols"] += int(net > 0)
                    sums["backtest_net_pnl"] += net
                    sums["exposure_pct"] += _number(test.get("exposure_pct"))
                    capital = _number(test.get("initial_capital"))
                    if capital > 0:
                        sums["peak_deployed_pct"] += (
                            100 * _number(test.get("max_capital_committed")) / capital
                        )
                    for name in ("start_date", "end_date"):
                        if test.get(name):
                            group["dates"].append(_stamp(test[name]).date().isoformat())
                    local_trades = [
                        trade
                        for trade in trades
                        if trade.get("strategy_id") == key
                        and trade.get("mode") == mode
                        and trade.get("membership", {}).get(universe) is True
                    ]
                    entry_dates = Counter()
                    for trade in local_trades:
                        net = _number(trade.get("net_pnl"))
                        counts["trades"] += 1
                        counts[
                            "wins"
                            if net > 0
                            else "losses"
                            if net < 0
                            else "flat_trades"
                        ] += 1
                        sums["winning_net_pnl" if net > 0 else "losing_net_pnl"] += net
                        for name in ("net_pnl", "gross_pnl", "transaction_costs"):
                            sums[name] += _number(trade.get(name))
                        price, quantity = (
                            _number(trade.get("entry_price")),
                            _number(trade.get("quantity")),
                        )
                        sums["entry_notional"] += price * quantity
                        if price > 0:
                            sums["reference_distance_pct"] += (
                                100 * _number(trade.get("risk_per_share")) / price
                            )
                        counts["partial_profit_trades"] += int(
                            trade.get("partial_taken") is True
                        )
                        entered, exited = (
                            _stamp(trade["entry_at"]),
                            _stamp(trade["exit_at"]),
                        )
                        elapsed = (exited - entered).total_seconds() / 60
                        if elapsed < 0:
                            raise ValueError("Invalid saved trade chronology")
                        sums["holding_minutes"] += elapsed
                        day = entered.date().isoformat()
                        group["first_trade"] = min(group["first_trade"] or day, day)
                        group["last_trade"] = max(group["last_trade"] or day, day)
                        counts["same_day_exits"] += int(entered.date() == exited.date())
                        counts["exits_within_15_minutes"] += int(elapsed <= 15)
                        entry_dates[entered.date()] += 1
                        legs = trade.get("exit_legs") or [trade]
                        for leg in legs:
                            reason = leg.get("exit_reason")
                            reason = reason if reason in EXITS else "OTHER"
                            exit_row = group["exits"].setdefault(reason, Counter())
                            exit_row["fills"] += 1
                            for name in ("net_pnl", "gross_pnl", "transaction_costs"):
                                exit_row[name] += _number(leg.get(name))
                    counts["additional_same_day_entries"] += sum(
                        max(0, count - 1) for count in entry_dates.values()
                    )
    except (
        OSError,
        sqlite3.Error,
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
    ):
        return {"status": "unavailable", "rows": []}
    rows = []
    for (key, mode), group in sorted(groups.items()):
        counts, sums = group["counts"], group["sums"]
        count, completed = counts["trades"], counts["completed_symbols"]
        rows.append(
            {
                "strategy_id": key,
                "mode": mode,
                "counts": dict(counts),
                "test_start": min(group["dates"]) if group["dates"] else None,
                "test_end": max(group["dates"]) if group["dates"] else None,
                "first_trade_date": group["first_trade"],
                "last_trade_date": group["last_trade"],
                "traded_symbol_profitable_pct": _mean(
                    100 * counts["profitable_traded_symbols"], counts["traded_symbols"]
                ),
                "traded_symbol_median_return_pct": round(
                    median(group["active_returns"]), 4
                )
                if group["active_returns"]
                else None,
                "mean_exposure_pct": _mean(sums["exposure_pct"], completed),
                "mean_peak_deployed_pct": _mean(sums["peak_deployed_pct"], completed),
                "mean_entry_notional": _mean(sums["entry_notional"], count),
                "mean_reference_distance_pct": _mean(
                    sums["reference_distance_pct"], count
                ),
                "mean_holding_minutes": _mean(sums["holding_minutes"], count),
                "mean_winner": _mean(sums["winning_net_pnl"], counts["wins"]),
                "mean_loser": _mean(sums["losing_net_pnl"], counts["losses"]),
                "net_pnl": round(sums["net_pnl"], 2),
                "gross_pnl_before_fees": round(sums["gross_pnl"], 2),
                "transaction_costs": round(sums["transaction_costs"], 2),
                "trade_to_backtest_net_difference": round(
                    sums["net_pnl"] - sums["backtest_net_pnl"], 2
                ),
                "exits": {
                    reason: {name: round(value, 2) for name, value in values.items()}
                    for reason, values in sorted(group["exits"].items())
                },
            }
        )
    return {"status": "available", "rows": rows}
