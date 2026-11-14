"""One chronological account over per-stock calendars, with auditable admissions."""

import math
from collections import Counter

import pandas as pd

from scanner.portfolio_policy import ACCOUNT_CAPITAL, allocate_candidates
from scanner.weekly_account_policy import VERSION, net_bracket
from scanner.weekly_floor import STRATEGY_ID, weekly_signal


def drawdown(values):
    peak, worst = ACCOUNT_CAPITAL, 0.0
    for value in values:
        peak = max(peak, value)
        worst = max(worst, (peak - value) / peak * 100)
    return worst


def winner_dependence(trades):
    profits = sorted((t["net_pnl"] for t in trades if t["net_pnl"] > 0), reverse=True)
    total = math.fsum(t["net_pnl"] for t in trades)
    wins = math.fsum(profits)
    return {
        "largest_winner": profits[0] if profits else 0.0,
        "top_1_share_of_gross_profits_pct": sum(profits[:1]) / wins * 100
        if wins
        else 0,
        "top_5_share_of_gross_profits_pct": sum(profits[:5]) / wins * 100
        if wins
        else 0,
        "net_profit_without_top_1": total - sum(profits[:1]),
        "net_profit_without_top_5": total - sum(profits[:5]),
    }


def simulate_account(
    frames,
    weekly,
    annual,
    policy,
    *,
    cost_bps=12,
    slippage_bps=5,
    tick_size=0.05,
    progress=None,
    benchmark=None,
    start=None,
):
    if not frames:
        raise ValueError("No completed stock histories")
    if cost_bps != 12 or slippage_bps != 5:
        raise ValueError("First comparison requires 12 bps fees and 5 bps slippage")
    rate, slip = cost_bps / 10000, slippage_bps / 10000
    calendar = pd.DatetimeIndex(
        sorted(set().union(*(set(f.index) for f in frames.values())))
    )
    if start is not None:
        calendar = calendar[calendar >= start]
    if calendar.empty:
        raise ValueError("No sessions in the requested period")
    # Sparse observations, not synthetic forward-filled execution candles.
    observations, events = {}, {}
    for symbol in sorted(frames):
        frame = frames[symbol]
        for row in frame.loc[calendar[0] :].itertuples():
            observations.setdefault(row.Index, {})[symbol] = row
        for signal_at, row in weekly[symbol].iterrows():
            offset = frame.index.searchsorted(signal_at, side="right")
            if offset < len(frame) and frame.index[offset] - signal_at <= pd.Timedelta(
                days=10
            ):
                stamp = frame.index[offset]
                if stamp < calendar[0]:
                    continue
                try:
                    signal = weekly_signal(
                        row,
                        tick_size=tick_size,
                        pivots=annual[symbol].get(stamp.year, {}),
                    )
                except ValueError:
                    continue  # Own warm-up / prior annual history not ready yet.
                if signal["signal"] == "BUY":
                    events.setdefault(stamp, []).append((symbol, signal_at, signal))
    cash, fees, slippage = ACCOUNT_CAPITAL, 0.0, 0.0
    positions, marks, mark_dates = {}, {}, {}
    trades, curve, admissions, skipped = [], [], [], []
    benchmark_start = None
    peak_count, peak_committed, minimum_cash = 0, 0.0, cash

    def equity():
        return cash + math.fsum(p["quantity"] * marks[s] for s, p in positions.items())

    def open_risk():
        return math.fsum(p["planned_open_risk"] for p in positions.values())

    def reject(symbol, stamp, reason, **evidence):
        skipped.append(
            {"symbol": symbol, "at": stamp.isoformat(), "reason": reason, **evidence}
        )

    def exit_position(symbol, raw, stamp, reason):
        nonlocal cash, fees, slippage
        p = positions.pop(symbol)
        fill = raw * (1 - slip)
        fee = p["quantity"] * fill * rate
        cash += p["quantity"] * fill - fee
        fees += fee
        slippage += p["quantity"] * raw * slip
        gross = (fill - p["entry_price"]) * p["quantity"]
        trades.append(
            {
                **p,
                "symbol": symbol,
                "strategy_id": STRATEGY_ID,
                "trade_number": len(trades) + 1,
                "exit_at": stamp.isoformat(),
                "exit_price": fill,
                "exit_reason": reason,
                "gross_pnl": gross,
                "transaction_costs": p["entry_cost"] + fee,
                "net_pnl": gross - p["entry_cost"] - fee,
                "terminal_liquidation": reason.startswith("END_OF_TEST"),
                "exit_mark_stale_days": (
                    stamp.normalize() - mark_dates[symbol].normalize()
                ).days
                if reason.startswith("END_OF_TEST")
                else 0,
            }
        )

    for offset, stamp in enumerate(calendar):
        rows = observations[stamp]
        if progress and (offset % 10 == 0 or offset == len(calendar) - 1):
            progress(offset + 1, len(calendar))
        for symbol, row in rows.items():
            marks[symbol], mark_dates[symbol] = float(row.open), stamp
        # Opening exits can release cash; intraday exits below cannot fund opens.
        for symbol in list(positions):
            if symbol not in rows:
                continue
            p, opening = positions[symbol], float(rows[symbol].open)
            if opening <= p["stoploss"]:
                exit_position(symbol, opening, stamp, "STOP_GAP")
            elif opening >= p["target2"]:
                exit_position(symbol, p["target2"], stamp, "YEARLY_R2")
        candidates = []
        for symbol, signal_at, signal in events.get(stamp, []):
            if symbol in positions:
                reject(symbol, stamp, "already_open")
                continue
            fill = float(rows[symbol].open) * (1 + slip)
            stop, target = signal["risk"]["stoploss"], signal["risk"]["target2"]
            details = net_bracket(fill, stop, target, rate, slip)
            if not 0 < stop < fill < target:
                reject(symbol, stamp, "opening_gap_invalidates_fixed_stop_or_R2")
                continue
            if (
                policy.stop_distance_ceiling is not None
                and details["stop_distance_fraction"]
                > policy.stop_distance_ceiling + 1e-12
            ):
                reject(symbol, stamp, "stop_distance_above_10pct", **details)
                continue
            if (
                policy.minimum_net_reward_risk is not None
                and details["net_reward_risk"] < policy.minimum_net_reward_risk - 1e-12
            ):
                reject(symbol, stamp, "net_reward_risk_below_1_5", **details)
                continue
            candidates.append(
                {
                    "symbol": symbol,
                    "signal": "BUY",
                    "score": signal["score"],
                    "entry": fill,
                    "stoploss": stop,
                    "target2": target,
                    "reward_risk": (target - fill) / (fill - stop),
                    "signal_at": signal_at,
                    **details,
                }
            )
        candidates.sort(key=lambda c: (-c["score"], -c["reward_risk"], c["symbol"]))
        baseline_budgets = {}
        if policy.risk_fraction is None:
            budget = max(
                0,
                min(
                    cash,
                    ACCOUNT_CAPITAL
                    - sum(p["capital_committed"] for p in positions.values()),
                ),
            )
            baseline_budgets = {
                c["symbol"]: c["allocation_budget"]
                for c in allocate_candidates(
                    candidates, budget=budget, slots=3 - len(positions)
                )
            }
        for c in candidates:
            symbol, fill = c["symbol"], c["entry"]
            if len(positions) >= 3:
                reject(symbol, stamp, "position_limit")
                continue
            before, existing_risk = equity(), open_risk()
            if policy.risk_fraction is None:
                allowance = baseline_budgets.get(symbol, 0)
                qty = math.floor(allowance / (fill * (1 + rate)))
            else:
                allowance = min(before * policy.allocation_fraction, cash / (1 + rate))
                qty = min(
                    math.floor(
                        before * policy.risk_fraction / c["planned_risk_per_share"]
                    ),
                    math.floor(allowance / fill),
                    math.floor(
                        max(0, before * policy.open_risk_fraction - existing_risk)
                        / c["planned_risk_per_share"]
                    ),
                )
            if qty < 1:
                reason = (
                    "open_risk_limit"
                    if policy.risk_fraction is not None
                    and before * policy.open_risk_fraction - existing_risk
                    < c["planned_risk_per_share"]
                    else "quantity_below_one"
                )
                reject(
                    symbol,
                    stamp,
                    reason,
                    equity_before_entry=before,
                    available_cash=cash,
                    existing_open_risk=existing_risk,
                )
                continue
            fee = qty * fill * rate
            admission = {
                "at": stamp.isoformat(),
                "symbol": symbol,
                "quantity": qty,
                "equity_before_entry": before,
                "cash_before_entry": cash,
                "existing_open_risk": existing_risk,
                "entry_fill": fill,
                "stoploss": c["stoploss"],
                "target2": c["target2"],
                "notional": qty * fill,
                "planned_open_risk": qty * c["planned_risk_per_share"],
                **{
                    k: c[k]
                    for k in (
                        "planned_risk_per_share",
                        "net_reward_per_share",
                        "net_reward_risk",
                        "stop_distance_fraction",
                    )
                },
            }
            admissions.append(admission)
            cash -= qty * fill + fee
            fees += fee
            slippage += qty * float(rows[symbol].open) * slip
            positions[symbol] = {
                "side": "LONG",
                "quantity": qty,
                "entry_at": stamp.isoformat(),
                "entry_signal_at": c["signal_at"].isoformat(),
                "entry_price": fill,
                "entry_cost": fee,
                "stoploss": c["stoploss"],
                "initial_stoploss": c["stoploss"],
                "target2": c["target2"],
                "capital_committed": qty * fill,
                "allocation_budget": allowance,
                "planned_open_risk": admission["planned_open_risk"],
            }
        minimum_cash = min(minimum_cash, cash)
        peak_count = max(peak_count, len(positions))
        peak_committed = max(
            peak_committed, sum(p["capital_committed"] for p in positions.values())
        )
        for symbol in list(positions):
            if symbol not in rows:
                continue
            p, row = positions[symbol], rows[symbol]
            if row.low <= p["stoploss"]:
                exit_position(
                    symbol,
                    min(float(row.open), p["stoploss"]),
                    stamp,
                    "PROTECTIVE_STOP",
                )
            elif row.high >= p["target2"]:
                exit_position(symbol, p["target2"], stamp, "YEARLY_R2")
        for symbol, row in rows.items():
            marks[symbol] = float(row.close)
        account_equity = equity()
        exposure = sum(p["quantity"] * marks[s] for s, p in positions.items())
        benchmark_equity = None
        if benchmark is not None and stamp in benchmark.index:
            close = float(benchmark.loc[stamp, "close"])
            if benchmark_start is None:
                benchmark_start = close
            benchmark_equity = ACCOUNT_CAPITAL * close / benchmark_start
        curve.append(
            {
                "date": (
                    stamp.normalize() + pd.Timedelta(hours=15, minutes=30)
                ).isoformat(),
                "equity": account_equity,
                "cash": cash,
                "capital_committed": sum(
                    p["capital_committed"] for p in positions.values()
                ),
                "gross_exposure": exposure,
                "exposure_pct": exposure / account_equity * 100
                if account_equity
                else 0,
                "planned_open_risk": open_risk(),
                "open_positions": len(positions),
                "stale_mark_symbols": [s for s in positions if s not in rows],
                "benchmark_equity": benchmark_equity,
            }
        )
    # Separate terminal assumptions from the daily MTM observations.
    terminal_stamp = pd.Timestamp(curve[-1]["date"])
    equity_before_terminal = equity()
    for symbol in list(positions):
        exit_position(symbol, marks[symbol], terminal_stamp, "END_OF_TEST")
    terminal = [t for t in trades if t["terminal_liquidation"]]
    profits = math.fsum(max(0, t["net_pnl"]) for t in trades)
    losses = -math.fsum(min(0, t["net_pnl"]) for t in trades)
    peak = ACCOUNT_CAPITAL
    for point in curve:
        peak = max(peak, point["equity"])
        point["drawdown_pct"] = (peak - point["equity"]) / peak * 100
    metrics = {
        "initial_capital": ACCOUNT_CAPITAL,
        "final_capital": cash,
        "net_profit": cash - ACCOUNT_CAPITAL,
        "return_pct": (cash / ACCOUNT_CAPITAL - 1) * 100,
        "total_trades": len(trades),
        "win_rate": sum(t["net_pnl"] > 0 for t in trades) / max(1, len(trades)) * 100,
        "profit_factor": profits / losses if losses else None if profits else 0,
        "max_drawdown_pct": drawdown([p["equity"] for p in curve]),
        "max_drawdown_after_terminal_pct": drawdown(
            [p["equity"] for p in curve] + [cash]
        ),
        "final_equity_before_terminal": equity_before_terminal,
        "terminal_liquidation_drag": equity_before_terminal - cash,
        "terminal_liquidations": len(terminal),
        "terminal_net_pnl": sum(t["net_pnl"] for t in terminal),
        "closed_before_terminal_net_pnl": sum(
            t["net_pnl"] for t in trades if not t["terminal_liquidation"]
        ),
        "transaction_costs": fees,
        "slippage_impact_estimate": slippage,
        "deployment_limit": ACCOUNT_CAPITAL,
        "cash_reserve": 0,
        "max_positions": 3,
        "max_observed_positions": peak_count,
        "max_capital_committed": peak_committed,
        "minimum_cash": minimum_cash,
        "skipped_trades": len(skipped),
        "skip_reasons": dict(Counter(r["reason"] for r in skipped)),
        **winner_dependence(trades),
    }
    return {
        "metrics": metrics,
        "trades": trades,
        "equity_curve": curve,
        "allocations": admissions,
        "rejected_entries": skipped,
        "terminal_liquidations": terminal,
        "bars": len(calendar),
        "start_date": calendar[0].isoformat(),
        "end_date": curve[-1]["date"],
        "engine": {"name": "WeeklySharedAccount", "version": VERSION},
        "account_policy": policy.to_dict(),
    }
