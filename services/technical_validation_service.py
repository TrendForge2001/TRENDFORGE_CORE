"""R71.5 NIFTY 100/200/500 technical strategy validation service."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import median
from typing import Any
from uuid import uuid4

import pandas as pd

from backtest.technical_realistic_engine import (
    TechnicalRealisticBacktestEngine,
    TechnicalRealisticConfig,
)
from providers.nse_broad_market_constituents import (
    NSEBroadMarketConstituentProvider,
)
from scanner.technical_strategy import (
    entry_decision,
    exit_decision,
    latest_signal,
    strategy_profile,
)


class TechnicalValidationService:
    VERSION = "R71.5-v1"
    UNIVERSES = ("NIFTY 100", "NIFTY 200", "NIFTY 500")
    DEFAULT_MODE_ASSUMPTIONS = {
        "intraday": {
            "period": "60d",
            "cost_bps": 4.0,
            "slippage_bps": 5.0,
        },
        "swing": {
            "period": "2y",
            "cost_bps": 12.0,
            "slippage_bps": 5.0,
        },
    }

    def __init__(
        self,
        *,
        technical_service: Any,
        universe_provider: NSEBroadMarketConstituentProvider | None = None,
    ) -> None:
        if technical_service is None:
            raise ValueError("technical_service is required")
        self.technical = technical_service
        self.market_data = technical_service.market_data
        self.indicators = technical_service.indicators
        self.universe_provider = (
            universe_provider or NSEBroadMarketConstituentProvider()
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _chunks(values: list[str], size: int):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _members(payload: dict[str, Any]) -> set[str]:
        return {
            str(item.get("symbol") or "").strip().upper()
            for item in payload.get("members") or []
            if str(item.get("symbol") or "").strip()
        }

    @classmethod
    def _membership(
        cls,
        symbol: str,
        sets: dict[str, set[str]],
    ) -> dict[str, bool]:
        return {
            "in_nifty100": symbol in sets["NIFTY 100"],
            "in_nifty200": symbol in sets["NIFTY 200"],
            "in_nifty500": symbol in sets["NIFTY 500"],
        }

    @staticmethod
    def _belongs(row: dict[str, Any], universe: str) -> bool:
        key = {
            "NIFTY 100": "in_nifty100",
            "NIFTY 200": "in_nifty200",
            "NIFTY 500": "in_nifty500",
        }[universe]
        return bool(row.get(key))

    def _aggregate(
        self,
        *,
        scanner_rows: list[dict[str, Any]],
        backtests: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        capital: float,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for universe in self.UNIVERSES:
            for mode in ("swing", "intraday"):
                scan = [
                    row for row in scanner_rows
                    if row.get("mode") == mode and self._belongs(row, universe)
                ]
                tests = [
                    row for row in backtests
                    if row.get("mode") == mode and self._belongs(row, universe)
                ]
                completed = [
                    row for row in tests if row.get("status") == "completed"
                ]
                universe_trades = [
                    row for row in trades
                    if row.get("mode") == mode and self._belongs(row, universe)
                ]
                wins = [
                    row for row in universe_trades
                    if self._finite(row.get("net_pnl")) > 0
                ]
                losses = [
                    row for row in universe_trades
                    if self._finite(row.get("net_pnl")) <= 0
                ]
                net_pnl = sum(self._finite(row.get("net_profit")) for row in completed)
                total_initial = len(completed) * float(capital)
                total_final = sum(
                    self._finite(row.get("final_capital")) for row in completed
                )
                gross_profit = sum(
                    max(0.0, self._finite(row.get("net_pnl")))
                    for row in universe_trades
                )
                gross_loss = abs(
                    sum(
                        min(0.0, self._finite(row.get("net_pnl")))
                        for row in universe_trades
                    )
                )
                returns = [
                    self._finite(row.get("return_pct")) for row in completed
                ]
                drawdowns = [
                    self._finite(row.get("max_drawdown_pct")) for row in completed
                ]
                output.append(
                    {
                        "universe": universe,
                        "mode": mode,
                        "requested_symbols": len(scan),
                        "completed_symbols": len(completed),
                        "error_symbols": len(
                            [row for row in tests if row.get("status") == "error"]
                        ),
                        "buy_signals": len(
                            [row for row in scan if row.get("signal") == "BUY"]
                        ),
                        "hold_signals": len(
                            [row for row in scan if row.get("signal") == "HOLD"]
                        ),
                        "exit_signals": len(
                            [row for row in scan if row.get("signal") == "EXIT"]
                        ),
                        "scanner_errors": len(
                            [row for row in scan if row.get("signal") == "ERROR"]
                        ),
                        "independent_capital_per_symbol": round(float(capital), 2),
                        "aggregate_test_capital": round(total_initial, 2),
                        "aggregate_final_capital": round(total_final, 2),
                        "net_pnl": round(net_pnl, 2),
                        "return_on_aggregate_test_capital_pct": round(
                            net_pnl * 100.0 / total_initial if total_initial else 0.0,
                            4,
                        ),
                        "average_symbol_return_pct": round(
                            sum(returns) / len(returns) if returns else 0.0,
                            4,
                        ),
                        "median_symbol_return_pct": round(
                            median(returns) if returns else 0.0,
                            4,
                        ),
                        "profitable_symbols": len(
                            [row for row in completed if self._finite(row.get("net_profit")) > 0]
                        ),
                        "loss_making_symbols": len(
                            [row for row in completed if self._finite(row.get("net_profit")) <= 0]
                        ),
                        "total_trades": len(universe_trades),
                        "trade_wins": len(wins),
                        "trade_losses": len(losses),
                        "trade_win_rate_pct": round(
                            len(wins) * 100.0 / len(universe_trades)
                            if universe_trades else 0.0,
                            4,
                        ),
                        "profit_factor": (
                            round(gross_profit / gross_loss, 4)
                            if gross_loss > 0
                            else None
                            if gross_profit > 0
                            else 0.0
                        ),
                        "average_max_drawdown_pct": round(
                            sum(drawdowns) / len(drawdowns) if drawdowns else 0.0,
                            4,
                        ),
                        "worst_max_drawdown_pct": round(
                            max(drawdowns) if drawdowns else 0.0,
                            4,
                        ),
                        "transaction_costs": round(
                            sum(self._finite(row.get("transaction_costs")) for row in completed),
                            2,
                        ),
                        "slippage_impact_estimate": round(
                            sum(self._finite(row.get("slippage_impact_estimate")) for row in completed),
                            2,
                        ),
                    }
                )
        return output

    def _monthly_pnl(
        self,
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
        for universe in self.UNIVERSES:
            for trade in trades:
                if not self._belongs(trade, universe):
                    continue
                try:
                    stamp = pd.Timestamp(trade.get("exit_at"))
                    month = stamp.strftime("%Y-%m")
                except Exception:
                    month = "unknown"
                key = (universe, str(trade.get("mode")), month)
                bucket = buckets.setdefault(
                    key,
                    {
                        "universe": universe,
                        "mode": str(trade.get("mode")),
                        "month": month,
                        "trades": 0,
                        "wins": 0,
                        "losses": 0,
                        "gross_pnl": 0.0,
                        "transaction_costs": 0.0,
                        "net_pnl": 0.0,
                    },
                )
                net = self._finite(trade.get("net_pnl"))
                bucket["trades"] += 1
                bucket["wins"] += int(net > 0)
                bucket["losses"] += int(net <= 0)
                bucket["gross_pnl"] += self._finite(trade.get("gross_pnl"))
                bucket["transaction_costs"] += self._finite(
                    trade.get("transaction_costs")
                )
                bucket["net_pnl"] += net
        output = []
        for key in sorted(buckets):
            row = dict(buckets[key])
            for field in ("gross_pnl", "transaction_costs", "net_pnl"):
                row[field] = round(float(row[field]), 2)
            output.append(row)
        return output

    def run(
        self,
        *,
        capital: float = 100_000.0,
        chunk_size: int = 25,
        force_refresh_universes: bool = True,
        mode_assumptions: dict[str, dict[str, float | str]] | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_id or "").strip() or f"r715-{uuid4().hex[:16]}"
        capital = float(capital)
        if not math.isfinite(capital) or capital < 1_000:
            raise ValueError("capital must be at least 1000")
        chunk_size = max(1, min(50, int(chunk_size)))
        assumptions = {
            mode: dict(values)
            for mode, values in self.DEFAULT_MODE_ASSUMPTIONS.items()
        }
        for mode, values in (mode_assumptions or {}).items():
            if mode in assumptions and isinstance(values, dict):
                assumptions[mode].update(values)

        started_at = self._timestamp()
        universe_payloads = self.universe_provider.load_all(
            force_refresh=force_refresh_universes
        )
        membership_sets = {
            name: self._members(payload)
            for name, payload in universe_payloads.items()
        }
        master_symbols = sorted(
            membership_sets["NIFTY 500"]
            | membership_sets["NIFTY 200"]
            | membership_sets["NIFTY 100"]
        )

        scanner_rows: list[dict[str, Any]] = []
        backtests: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        for mode in ("swing", "intraday"):
            profile = strategy_profile(mode)
            settings = assumptions[mode]
            period = str(settings.get("period") or profile.default_period)
            cost_bps = float(settings.get("cost_bps") or 0.0)
            slippage_bps = float(settings.get("slippage_bps") or 0.0)

            for batch_number, chunk in enumerate(
                self._chunks(master_symbols, chunk_size),
                start=1,
            ):
                frames, failures = self.market_data.batch_candles_with_errors(
                    chunk,
                    period=period,
                    interval=profile.interval,
                )
                for symbol in chunk:
                    memberships = self._membership(symbol, membership_sets)
                    raw = frames.get(symbol)
                    if raw is None:
                        error = str(
                            failures.get(symbol)
                            or "Kite returned no historical candle data"
                        )
                        scanner_rows.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "period": period,
                                "interval": profile.interval,
                                "signal": "ERROR",
                                "score": 0.0,
                                "confidence": 0.0,
                                "error": error,
                                **memberships,
                            }
                        )
                        backtests.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "status": "error",
                                "error": error,
                                **memberships,
                            }
                        )
                        errors.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "phase": "market_data",
                                "batch": batch_number,
                                "error": error,
                                **memberships,
                            }
                        )
                        continue

                    try:
                        completed = self.technical._completed_bars(
                            raw,
                            interval=profile.interval,
                        )
                        if len(completed) < 60:
                            raise ValueError(
                                "At least 60 completed candles are required"
                            )
                        frame = self.indicators.calculate(completed.copy())
                        signal = latest_signal(frame, profile)
                        risk = signal.get("risk") or {}
                        scanner_rows.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "period": period,
                                "interval": profile.interval,
                                "bar_at": self.technical._date_label(frame.index[-1]),
                                "signal": signal.get("signal"),
                                "score": signal.get("score"),
                                "confidence": signal.get("confidence"),
                                "trigger": signal.get("trigger"),
                                "entry": risk.get("entry"),
                                "stoploss": risk.get("stoploss"),
                                "target2": risk.get("target2"),
                                "reward_risk": risk.get("reward_risk"),
                                **memberships,
                            }
                        )

                        def entry_rule(previous, current):
                            if (
                                mode == "intraday"
                                and not self.technical._intraday_entry_window_open(current)
                            ):
                                return None
                            return entry_decision(previous, current, profile)

                        def exit_rule(previous, current):
                            return exit_decision(previous, current, profile)

                        simulation = TechnicalRealisticBacktestEngine(
                            TechnicalRealisticConfig(
                                initial_capital=capital,
                                cost_bps=cost_bps,
                                slippage_bps=slippage_bps,
                                force_final_exit=True,
                                same_bar_priority="stop",
                                intraday_exit_hour=15,
                                intraday_exit_minute=0,
                            )
                        ).run(
                            frame,
                            entry_rule=entry_rule,
                            exit_rule=exit_rule,
                            mode=mode,
                        )
                        metrics = simulation.metrics
                        backtests.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "status": "completed",
                                "period": period,
                                "interval": profile.interval,
                                "start_date": self.technical._date_label(frame.index[0]),
                                "end_date": self.technical._date_label(frame.index[-1]),
                                "bars": len(frame),
                                "initial_capital": metrics.get("initial_capital"),
                                "final_capital": metrics.get("final_capital"),
                                "net_profit": metrics.get("net_profit"),
                                "return_pct": metrics.get("return_pct"),
                                "buy_hold_return_pct": metrics.get("buy_hold_return_pct"),
                                "excess_vs_buy_hold_pct": metrics.get("excess_vs_buy_hold_pct"),
                                "total_trades": metrics.get("total_trades"),
                                "wins": metrics.get("wins"),
                                "losses": metrics.get("losses"),
                                "win_rate": metrics.get("win_rate"),
                                "profit_factor": metrics.get("profit_factor"),
                                "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                                "sharpe_ratio": metrics.get("sharpe_ratio"),
                                "exposure_pct": metrics.get("exposure_pct"),
                                "transaction_costs": metrics.get("transaction_costs"),
                                "slippage_impact_estimate": metrics.get(
                                    "slippage_impact_estimate"
                                ),
                                "atr_stop_exits": metrics.get("atr_stop_exits"),
                                "atr_target_exits": metrics.get("atr_target_exits"),
                                "session_exits": metrics.get("session_exits"),
                                **memberships,
                            }
                        )
                        for trade in simulation.trades:
                            trades.append(
                                {
                                    "symbol": symbol,
                                    "mode": mode,
                                    "period": period,
                                    "interval": profile.interval,
                                    **trade,
                                    **memberships,
                                }
                            )
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        if not any(
                            row.get("symbol") == symbol
                            and row.get("mode") == mode
                            for row in scanner_rows
                        ):
                            scanner_rows.append(
                                {
                                    "symbol": symbol,
                                    "mode": mode,
                                    "period": period,
                                    "interval": profile.interval,
                                    "signal": "ERROR",
                                    "score": 0.0,
                                    "confidence": 0.0,
                                    "error": error,
                                    **memberships,
                                }
                            )
                        backtests.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "status": "error",
                                "error": error,
                                **memberships,
                            }
                        )
                        errors.append(
                            {
                                "symbol": symbol,
                                "mode": mode,
                                "phase": "analysis_or_backtest",
                                "batch": batch_number,
                                "error": error,
                                **memberships,
                            }
                        )

        aggregate = self._aggregate(
            scanner_rows=scanner_rows,
            backtests=backtests,
            trades=trades,
            capital=capital,
        )
        monthly_pnl = self._monthly_pnl(trades)
        observation = {}
        method = getattr(self.market_data, "observability_snapshot", None)
        if callable(method):
            try:
                observation = method(master_symbols)
            except Exception:
                observation = {}

        completed_at = self._timestamp()
        return {
            "status": "completed",
            "version": self.VERSION,
            "run_id": run_id,
            "started_at": started_at,
            "completed_at": completed_at,
            "data_policy": "kite_only",
            "fundamentals_used": False,
            "enrichment_used": False,
            "broker_orders_allowed": False,
            "paper_orders_created": False,
            "universe_fetch_policy": "official_nse_csv",
            "master_symbol_count": len(master_symbols),
            "universe_metadata": {
                name: {
                    key: value
                    for key, value in payload.items()
                    if key != "members"
                }
                for name, payload in universe_payloads.items()
            },
            "assumptions": {
                "independent_capital_per_symbol": round(capital, 2),
                "aggregation_note": (
                    "Each symbol is backtested independently with the stated "
                    "capital; aggregate P/L is not a concurrent portfolio."
                ),
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "modes": assumptions,
            },
            "scanner_results": scanner_rows,
            "backtest_results": backtests,
            "trades": trades,
            "aggregate": aggregate,
            "monthly_pnl": monthly_pnl,
            "errors": errors,
            "provider_observation": observation,
        }


__all__ = ["TechnicalValidationService"]
