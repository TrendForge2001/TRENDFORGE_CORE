"""Shared-cash weekly signals with next-session fills and daily protective exits."""

import math

import pandas as pd

from scanner.portfolio_policy import (
    ACCOUNT_CAPITAL,
    CASH_RESERVE,
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
    allocate_candidates,
    number,
    risk_details,
)
from scanner.weekly_floor import STRATEGY_ID, VERSION, weekly_signal


def simulate_weekly(
    frames,
    weekly,
    annual,
    *,
    cost_bps=12.0,
    slippage_bps=5.0,
    tick_size=0.05,
    progress=None,
):
    from backtest.portfolio_engine import SharedPortfolioEngine

    for value in (cost_bps, slippage_bps):
        if number(value) is None or not 0 <= value <= 1000:
            raise ValueError("Costs and slippage must be between 0 and 1000 bps")
    frames = SharedPortfolioEngine.align(frames)
    index = next(iter(frames.values())).index
    rate, slip = cost_bps / 10000, slippage_bps / 10000
    cash, fees, slippage = ACCOUNT_CAPITAL, 0.0, 0.0
    positions, trades, curve, allocations, rejected = {}, [], [], [], []
    events = {}
    for symbol in frames:
        for stamp, row in weekly[symbol].iterrows():
            offset = index.searchsorted(stamp, side="right")
            if offset < len(index) and index[offset] - stamp <= pd.Timedelta(days=10):
                events.setdefault(index[offset], []).append((symbol, stamp, row))
    peak_positions, peak_deployed, minimum_cash = 0, 0.0, cash

    def exit_position(symbol, raw, stamp, reason):
        nonlocal cash, fees, slippage
        position = positions.pop(symbol)
        fill = raw * (1 - slip)
        fee = position["quantity"] * fill * rate
        gross = (fill - position["entry_price"]) * position["quantity"]
        cash += position["quantity"] * fill - fee
        fees += fee
        slippage += position["quantity"] * raw * slip
        trades.append(
            {
                **position,
                "symbol": symbol,
                "strategy_id": STRATEGY_ID,
                "trade_number": len(trades) + 1,
                "exit_at": stamp.isoformat(),
                "exit_price": fill,
                "exit_reason": reason,
                "gross_pnl": gross,
                "transaction_costs": position["entry_cost"] + fee,
                "net_pnl": gross - position["entry_cost"] - fee,
            }
        )

    for offset, stamp in enumerate(index):
        rows = {symbol: frame.iloc[offset] for symbol, frame in frames.items()}
        if progress and (offset % 10 == 0 or offset == len(index) - 1):
            progress(offset + 1, len(index))
        # Known opening gaps can release cash before same-open entries. Later
        # intraday exits cannot finance earlier opening fills.
        for symbol in list(positions):
            position, opening = positions[symbol], float(rows[symbol].open)
            if opening <= position["stoploss"]:
                exit_position(symbol, opening, stamp, "STOP_GAP")
            elif opening >= position["target2"]:
                exit_position(symbol, position["target2"], stamp, "YEARLY_R2")
        candidates = []
        for symbol, signal_at, row in events.get(stamp, []):
            if symbol in positions:
                continue
            try:
                # Annual levels are known at this entry date and frozen for the
                # position, including across a subsequent calendar-year rollover.
                signal = weekly_signal(
                    row, tick_size=tick_size, pivots=annual[symbol].get(stamp.year, {})
                )
            except ValueError:
                continue
            if signal["signal"] != "BUY":
                continue
            fill = float(rows[symbol].open) * (1 + slip)
            risk = signal["risk"]
            details = risk_details(fill, risk["stoploss"], risk["target2"])
            if details.get("reward_risk") is None:
                rejected.append(
                    {
                        "symbol": symbol,
                        "at": stamp.isoformat(),
                        "reason": "opening_gap_invalidates_fixed_stop_or_R2",
                    }
                )
                continue
            candidates.append(
                {
                    "symbol": symbol,
                    "signal": "BUY",
                    "score": signal["score"],
                    "entry": fill,
                    "stoploss": risk["stoploss"],
                    "target2": risk["target2"],
                    "signal_at": signal_at,
                    "indicators": signal["indicators"],
                    **details,
                }
            )
        committed = sum(p["capital_committed"] for p in positions.values())
        budget = max(0.0, min(cash, DEPLOYMENT_LIMIT - committed))
        selected = allocate_candidates(
            candidates, budget=budget, slots=MAX_POSITIONS - len(positions)
        )
        for candidate in selected:
            fill = candidate["entry"]
            qty = math.floor(candidate["allocation_budget"] / (fill * (1 + rate)))
            if qty <= 0:
                continue
            fee = qty * fill * rate
            cash -= qty * fill + fee
            fees += fee
            slippage += qty * float(rows[candidate["symbol"]].open) * slip
            position = {
                "side": "LONG",
                "quantity": qty,
                "entry_at": stamp.isoformat(),
                "entry_signal_at": candidate["signal_at"].isoformat(),
                "entry_price": fill,
                "entry_cost": fee,
                "stoploss": candidate["stoploss"],
                "initial_stoploss": candidate["stoploss"],
                "target2": candidate["target2"],
                "capital_committed": qty * fill,
                "allocation_budget": candidate["allocation_budget"],
                "indicators": candidate["indicators"],
            }
            positions[candidate["symbol"]] = position
            allocations.append(
                {
                    "at": stamp.isoformat(),
                    "symbol": candidate["symbol"],
                    "quantity": qty,
                    "allocation_budget": candidate["allocation_budget"],
                }
            )
        minimum_cash = min(minimum_cash, cash)
        peak_positions = max(peak_positions, len(positions))
        peak_deployed = max(
            peak_deployed, sum(p["capital_committed"] for p in positions.values())
        )
        for symbol in list(positions):
            position, row = positions[symbol], rows[symbol]
            if row.low <= position["stoploss"]:
                exit_position(
                    symbol,
                    min(float(row.open), position["stoploss"]),
                    stamp,
                    "PROTECTIVE_STOP",
                )
            elif row.high >= position["target2"]:
                exit_position(symbol, position["target2"], stamp, "YEARLY_R2")
        if offset == len(index) - 1:
            for symbol in list(positions):
                exit_position(
                    symbol,
                    float(rows[symbol].close),
                    stamp.normalize() + pd.Timedelta(hours=15, minutes=30),
                    "END_OF_TEST",
                )
        committed = sum(p["capital_committed"] for p in positions.values())
        equity = cash + sum(
            p["quantity"] * float(rows[symbol].close) for symbol, p in positions.items()
        )
        curve.append(
            {
                "date": (
                    stamp.normalize() + pd.Timedelta(hours=15, minutes=30)
                ).isoformat(),
                "equity": equity,
                "cash": cash,
                "capital_committed": committed,
                "open_positions": len(positions),
            }
        )
    profits = sum(max(0, t["net_pnl"]) for t in trades)
    losses = sum(min(0, t["net_pnl"]) for t in trades)
    peak, drawdown = ACCOUNT_CAPITAL, 0.0
    for point in curve:
        peak = max(peak, point["equity"])
        drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
    return {
        "metrics": {
            "initial_capital": ACCOUNT_CAPITAL,
            "final_capital": cash,
            "net_profit": cash - ACCOUNT_CAPITAL,
            "return_pct": (cash / ACCOUNT_CAPITAL - 1) * 100,
            "total_trades": len(trades),
            "win_rate": sum(t["net_pnl"] > 0 for t in trades)
            / max(1, len(trades))
            * 100,
            "profit_factor": profits / abs(losses)
            if losses
            else None
            if profits
            else 0.0,
            "max_drawdown_pct": drawdown,
            "transaction_costs": fees,
            "slippage_impact_estimate": slippage,
            "deployment_limit": DEPLOYMENT_LIMIT,
            "cash_reserve": CASH_RESERVE,
            "max_positions": MAX_POSITIONS,
            "max_observed_positions": peak_positions,
            "max_capital_committed": peak_deployed,
            "minimum_cash": minimum_cash,
        },
        "trades": trades,
        "equity_curve": curve,
        "allocations": allocations,
        "rejected_entries": rejected[:100],
        "bars": len(index),
        "start_date": index[0].isoformat(),
        "end_date": curve[-1]["date"],
        "engine": {"name": "WeeklyFloorDailyExecution", "version": VERSION},
    }
