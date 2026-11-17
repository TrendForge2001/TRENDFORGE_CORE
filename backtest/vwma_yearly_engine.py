"""Daily long-only pivot retests, conditional exits and staged annual targets.

Signals and close-confirmed exits fill at the next observed session open.
An opening gap can use only the previous completed RSI. R1 half exits and
the final R3 limit are known before each session; R2 continuation and trailing
references require a completed close and become effective next session.
"""

import math

import pandas as pd

from backtest.indicator_rows import indicator_rows
from scanner.portfolio_policy import MAX_POSITIONS, number
from scanner.vwma_yearly import (
    INDICATORS,
    STRATEGY_ID,
    VERSION,
    entry_plan,
    evaluate,
    opening_gap_exit,
    stop_conditions,
)


class VwmaYearlyBacktestEngine:
    VERSION = VERSION

    def __init__(self, *, strategy_engine=None):
        self.strategies = strategy_engine

    def validate(self, strategy_id, mode, interval, frames):
        if strategy_id != STRATEGY_ID or mode != "swing" or interval != "1d":
            raise ValueError("The VWMA yearly strategy requires completed daily swing candles")

    def indicator_keys(self, strategy_id):
        return INDICATORS

    def make_plan(self, strategy_id, row, tick, fill):
        return entry_plan(row, tick_size=tick, entry=fill)

    def entry_raw(self, candidate, row, stamp, mode):
        return float(row["open"])

    def evaluate_pair(self, previous, row, context, strategy_id):
        return evaluate(previous, row, context, strategy_id)

    def run(
        self,
        frames,
        *,
        strategy_id,
        mode,
        interval,
        cost_bps=12.0,
        slippage_bps=5.0,
        liquidity_confirmation=False,
        tick_size=0.05,
        short_borrow_available=False,
        initial_capital=100_000.0,
        progress=None,
    ):
        from backtest.portfolio_engine import SharedPortfolioEngine
        from scanner.multi_strategy_engine import EvaluationContext, MultiStrategyEngine

        self.validate(strategy_id, mode, interval, frames)
        keys = self.indicator_keys(strategy_id)
        costs, slippage, tick, capital = map(
            number, (cost_bps, slippage_bps, tick_size, initial_capital)
        )
        if (
            costs is None
            or slippage is None
            or not 0 <= costs <= 1000
            or not 0 <= slippage <= 1000
        ):
            raise ValueError("Costs and slippage must be between 0 and 1000 bps")
        if tick is None or not 0 < tick <= 100 or capital is None or capital < 1000:
            raise ValueError("Invalid daily research capital or tick size")
        frames = SharedPortfolioEngine.align(frames)
        index = next(iter(frames.values())).index
        rate, slip = costs / 10000, slippage / 10000
        cash = capital
        positions, pending, pending_exits = {}, [], {}
        trades, fills, allocations, curve, rejected = [], [], [], [], []
        rejection_counts = {}
        total_costs, total_slip = 0.0, 0.0
        peak_positions, peak_deployed, minimum_cash = 0, 0.0, capital
        context = EvaluationContext(mode=mode, interval=interval, tick_size=tick, liquidity_confirmation=liquidity_confirmation)
        iterators = {
            symbol: indicator_rows(
                frame, ("open", "high", "low", "close", "volume", *keys)
            )
            for symbol, frame in frames.items()
        }
        previous = {symbol: next(iterator) for symbol, iterator in iterators.items()}

        def reject(symbol, stamp, reason):
            rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
            if len(rejected) < 100:
                rejected.append(
                    {"symbol": symbol, "signal_at": stamp.isoformat(), "reason": reason}
                )

        def close_position(symbol, raw, stamp, reason, quantity=None, limit=None):
            nonlocal cash, total_costs, total_slip, minimum_cash
            position = positions[symbol]
            qty = position["remaining_quantity"] if quantity is None else quantity
            fill = float(raw) * (1 - slip)
            if limit is not None:
                fill = max(fill, limit)
            fee = qty * fill * rate
            gross = (fill - position["entry_price"]) * qty
            entry_fee = position["entry_cost"] * qty / position["quantity"]
            cash += qty * fill - fee
            total_costs += fee
            total_slip += qty * (float(raw) - fill)
            leg = {
                "symbol": symbol,
                "strategy_id": strategy_id,
                "side": "LONG",
                "entry_at": position["entry_at"],
                "exit_at": stamp.isoformat(),
                "quantity": qty,
                "entry_price": position["entry_price"],
                "exit_price": fill,
                "exit_reason": reason,
                "gross_pnl": gross,
                "transaction_costs": entry_fee + fee,
                "net_pnl": gross - entry_fee - fee,
            }
            position["exit_legs"].append(leg)
            fills.append(leg)
            position["remaining_quantity"] -= qty
            position["capital_committed"] = (
                position["remaining_quantity"] * position["entry_price"]
            )
            minimum_cash = min(minimum_cash, cash)
            if position["remaining_quantity"] == 0:
                positions.pop(symbol)
                legs = position["exit_legs"]
                trades.append(
                    {
                        **position,
                        "symbol": symbol,
                        "strategy_id": strategy_id,
                        "trade_number": len(trades) + 1,
                        "exit_at": stamp.isoformat(),
                        "exit_reason": reason,
                        "exit_price": sum(
                            leg["exit_price"] * leg["quantity"] for leg in legs
                        )
                        / position["quantity"],
                        "final_exit_price": fill,
                        "gross_pnl": sum(leg["gross_pnl"] for leg in legs),
                        "transaction_costs": sum(
                            leg["transaction_costs"] for leg in legs
                        ),
                        "net_pnl": sum(leg["net_pnl"] for leg in legs),
                    }
                )

        def observe(stamp, rows):
            market = sum(
                p["remaining_quantity"] * float(rows[s]["close"])
                for s, p in positions.items()
            )
            curve.append(
                {
                    "date": stamp.isoformat(),
                    "equity": cash + market,
                    "cash": cash,
                    "capital_committed": sum(
                        p["capital_committed"] for p in positions.values()
                    ),
                    "market_value": market,
                    "open_positions": len(positions),
                }
            )

        observe(index[0], previous)
        for offset in range(1, len(index)):
            stamp = index[offset]
            rows = {symbol: next(iterator) for symbol, iterator in iterators.items()}
            if progress is not None and (
                offset == 1 or offset % 10 == 0 or offset == len(index) - 1
            ):
                progress(offset, len(index) - 1)
            # Orders based on already completed data precede today's intrabar
            # targets. Current-session RSI must never be used for an open fill.
            for symbol in list(positions):
                if opening_gap_exit(previous[symbol], rows[symbol]):
                    close_position(
                        symbol, rows[symbol]["open"], stamp, "RSI_GAP_OPEN_EXIT"
                    )
                elif symbol in pending_exits:
                    close_position(
                        symbol, rows[symbol]["open"], stamp, pending_exits[symbol]
                    )
            pending_exits.clear()

            # Reserve at the opening snapshot; intraday target proceeds cannot
            # finance other entries in this same session.
            available = max(
                0.0,
                min(
                    capital - sum(p["capital_committed"] for p in positions.values()),
                    cash,
                ),
            )
            ranked = sorted(
                (
                    candidate
                    for candidate in pending
                    if candidate["symbol"] not in positions
                ),
                key=lambda candidate: (-candidate["score"], candidate["symbol"]),
            )[: max(0, MAX_POSITIONS - len(positions))]
            total_score = sum(candidate["score"] for candidate in ranked)
            opening_equity = cash + sum(
                p["remaining_quantity"] * float(rows[s]["open"])
                for s, p in positions.items()
            )
            for candidate in ranked:
                symbol = candidate["symbol"]
                raw = self.entry_raw(candidate, rows[symbol], stamp, mode)
                if raw is None:
                    reject(symbol, stamp, "next_candle_trigger_or_entry_window_not_met")
                    continue
                fill = raw * (1 + slip)
                plan = self.make_plan(strategy_id, candidate["signal_row"], tick, fill)
                if not plan:
                    reject(
                        symbol,
                        stamp,
                        "gap_or_slippage_failed_annual_target_or_second_support",
                    )
                    continue
                budget = available * candidate["score"] / total_score
                risk_budget = max(0.0, opening_equity) * 0.005
                reference_risk = (
                    plan["risk_per_share"] + fill * rate + plan["stoploss"] * rate
                )
                quantity = min(
                    math.floor(budget / (fill * (1 + rate))),
                    math.floor(risk_budget / reference_risk),
                )
                if quantity < 2:
                    reject(symbol, stamp, "risk_or_budget_cannot_support_partial_exit")
                    continue
                fee = quantity * fill * rate
                spent = quantity * fill + fee
                if spent > cash + 1e-7:
                    reject(symbol, stamp, "cash_budget_exceeded")
                    continue
                position = {
                    "entry_at": stamp.isoformat(),
                    "entry_signal_at": candidate["entry_signal_at"],
                    "entry_price": fill,
                    "entry_raw_price": raw,
                    "side": "LONG",
                    "quantity": quantity,
                    "remaining_quantity": quantity,
                    "entry_cost": fee,
                    "capital_committed": quantity * fill,
                    "allocation_budget": budget,
                    "weight_pct": candidate["score"] / total_score * 100,
                    "score": candidate["score"],
                    "stoploss": plan["stoploss"],
                    "initial_stoploss": plan["stoploss"],
                    "stop_is_resting_order": False,
                    "partial_target": plan["partial_target"],
                    "second_target": plan["second_target"],
                    "target": plan["target2"],
                    "pivot_levels": plan["pivot_levels"],
                    "pivot_year": pd.Timestamp(candidate["entry_signal_at"]).year,
                    "risk_per_share": plan["risk_per_share"],
                    "reward_risk": plan["reward_risk"],
                    "risk_reward": plan["risk_reward"],
                    "risk_budget": risk_budget,
                    "planned_initial_risk": quantity * reference_risk,
                    "sizing_reference_is_conditional": True,
                    "partial_taken": False,
                    "stop_reference_history": [],
                    "exit_legs": [],
                    "indicators": candidate["indicators"],
                    "technical_evidence": candidate["checks"],
                }
                positions[symbol] = position
                allocations.append(
                    {
                        "symbol": symbol,
                        **position,
                        "exit_legs": [],
                        "stop_reference_history": [],
                    }
                )
                cash -= spent
                total_costs += fee
                total_slip += quantity * raw * slip
                minimum_cash = min(minimum_cash, cash)
                peak_positions = max(peak_positions, len(positions))
                peak_deployed = max(
                    peak_deployed,
                    sum(p["capital_committed"] for p in positions.values()),
                )
            pending = []

            for symbol in list(positions):
                position, row = positions[symbol], rows[symbol]
                if mode == "intraday" and (stamp.hour, stamp.minute) >= (15, 0):
                    close_position(symbol, row["open"], stamp, "INTRADAY_SQUARE_OFF")
                    continue
                if (
                    not position["partial_taken"]
                    and float(row["high"]) >= position["partial_target"]
                ):
                    close_position(
                        symbol,
                        max(float(row["open"]), position["partial_target"]),
                        stamp,
                        "R1_PARTIAL_PROFIT",
                        position["quantity"] // 2,
                        limit=position["partial_target"],
                    )
                    position["partial_taken"] = True
                if (
                    position["partial_taken"]
                    and float(row["high"]) >= position["target"]
                ):
                    close_position(
                        symbol,
                        max(float(row["open"]), position["target"]),
                        stamp,
                        "R3_FINAL_TARGET",
                        limit=position["target"],
                    )

            if offset == len(index) - 1:
                for symbol in list(positions):
                    close_position(symbol, rows[symbol]["close"], stamp, "END_OF_TEST")
            if (
                len(positions) > MAX_POSITIONS
                or cash < -1e-6
                or sum(p["capital_committed"] for p in positions.values())
                > capital + 1e-6
            ):
                raise RuntimeError("Daily research portfolio capital invariant failed")
            observe(stamp, rows)
            if offset == len(index) - 1:
                continue
            for symbol, row in rows.items():
                evaluation = (
                    self.evaluate_pair(previous[symbol], row, context, strategy_id)
                    if self.strategies is None
                    or type(self.strategies) is MultiStrategyEngine
                    else self.strategies.evaluate(
                        frames[symbol].iloc[offset - 1 : offset + 1],
                        mode=mode,
                        interval=interval,
                        strategy_ids=[strategy_id],
                        tick_size=tick,
                        liquidity_confirmation=liquidity_confirmation,
                    )["evaluations"][0]
                )
                if symbol in positions:
                    position = positions[symbol]
                    checks = stop_conditions(
                        previous[symbol], row, position["stoploss"]
                    )
                    if checks["rsi_below_30_and_gap_down"]:
                        pending_exits[symbol] = "RSI_GAP_CLOSE_CONFIRMED_EXIT"
                    elif checks["selling_volume_and_close_below_support"]:
                        pending_exits[symbol] = "SELLING_VOLUME_SUPPORT_EXIT"
                    elif evaluation.get("exit_triggered"):
                        pending_exits[symbol] = "BEARISH_SETUP_EXIT"
                    elif position["partial_taken"]:
                        close, volume, average = map(
                            number,
                            (
                                row.get("close"),
                                row.get("volume"),
                                row.get("VOL_SMA_20"),
                            ),
                        )
                        confirmed = (
                            None not in (volume, average)
                            and average > 0
                            and volume > average
                        )
                        if float(row["high"]) >= position["second_target"] and not (
                            close > position["second_target"] and confirmed
                        ):
                            pending_exits[symbol] = "R2_CLOSE_CONFIRMED_PROFIT"
                        if confirmed:
                            cleared = [
                                position["pivot_levels"][name]
                                for name in ("R1", "R2")
                                if close > position["pivot_levels"][name]
                            ]
                            next_reference = max([position["stoploss"], *cleared])
                            if next_reference > position["stoploss"]:
                                position["stoploss"] = next_reference
                                position["stop_reference_history"].append(
                                    {
                                        "confirmed_at": stamp.isoformat(),
                                        "reference": next_reference,
                                    }
                                )
                elif evaluation.get("entry_state") == "ARMED":
                    pending.append(
                        {
                            "symbol": symbol,
                            "score": evaluation["score"],
                            "entry_signal_at": stamp.isoformat(),
                            "signal_row": row,
                            "entry_plan": evaluation.get("entry_plan", {}),
                            "checks": evaluation["checks"],
                            "indicators": {
                                key: number(row.get(key)) for key in keys
                            },
                        }
                    )
            previous = rows

        profits = sum(trade["net_pnl"] for trade in trades if trade["net_pnl"] > 0)
        losses = sum(trade["net_pnl"] for trade in trades if trade["net_pnl"] < 0)
        peak, drawdown = capital, 0.0
        for point in curve:
            peak = max(peak, point["equity"])
            drawdown = max(drawdown, (peak - point["equity"]) / peak * 100)
        return {
            "metrics": {
                "initial_capital": capital,
                "final_capital": cash,
                "net_profit": cash - capital,
                "return_pct": (cash / capital - 1) * 100,
                "total_trades": len(trades),
                "win_rate": sum(trade["net_pnl"] > 0 for trade in trades)
                / len(trades)
                * 100
                if trades
                else 0,
                "profit_factor": profits / abs(losses)
                if losses
                else None
                if profits
                else 0,
                "max_drawdown_pct": drawdown,
                "transaction_costs": total_costs,
                "slippage_impact_estimate": total_slip,
                "deployment_limit": capital,
                "cash_reserve": 0.0,
                "max_positions": MAX_POSITIONS,
                "max_observed_positions": peak_positions,
                "max_capital_committed": peak_deployed,
                "minimum_cash": minimum_cash,
            },
            "trades": trades,
            "exit_fills": fills,
            "equity_curve": curve,
            "allocations": allocations,
            "rejection_counts": rejection_counts,
            "rejection_samples": rejected,
            "start_date": index[0].isoformat(),
            "end_date": index[-1].isoformat(),
            "bars": len(index),
        }
