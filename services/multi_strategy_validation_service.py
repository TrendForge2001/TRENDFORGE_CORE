"""R72.5.3 multi-strategy backtest and validation service."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import median
from typing import Any, Callable
from uuid import uuid4

import pandas as pd

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from providers.nse_broad_market_constituents import normalize_index_name
from scanner.multi_strategy_engine import CONFIRMATION_ONLY, REVIEW_REQUIRED
from scanner.strategy_registry import get_strategy


ProgressCallback = Callable[[dict[str, Any]], None]


class MultiStrategyValidationService:
    VERSION = "R72.5.3-v1"
    UNIVERSES = ("NIFTY 100", "NIFTY 200", "NIFTY 500")
    MODES = ("intraday", "swing", "positional")
    DEFAULT_ASSUMPTIONS = {
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
        "positional": {
            "period": "5y",
            "cost_bps": 12.0,
            "slippage_bps": 5.0,
        },
    }
    VALIDATION_GATE = {
        "minimum_completed_symbols": 20,
        "minimum_universe_scope_pct": 90.0,
        "minimum_coverage_pct": 90.0,
        "minimum_total_trades": 30,
        "minimum_profitable_symbol_pct": 50.0,
        "minimum_profit_factor": 1.10,
        "minimum_median_symbol_return_pct_exclusive": 0.0,
        "maximum_average_drawdown_pct": 15.0,
        "maximum_worst_drawdown_pct": 35.0,
        "require_positive_net_pnl": True,
    }

    def __init__(self, *, scanner_service: Any) -> None:
        if scanner_service is None:
            raise ValueError("scanner_service is required")
        self.scanner = scanner_service
        self.market_data = scanner_service.market_data
        self.indicators = scanner_service.indicators
        self.strategy_engine = scanner_service.strategies
        self.universe_provider = scanner_service.universe_provider
        self.backtester = MultiStrategyBacktestEngine(
            strategy_engine=self.strategy_engine,
        )

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _finite(value: Any, default: float = 0.0) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @staticmethod
    def _chunks(values: list[str], size: int):
        for start in range(0, len(values), size):
            yield values[start : start + size]

    @staticmethod
    def _members(payload: dict[str, Any]) -> set[str]:
        return {
            str(item.get("symbol") or "").strip().upper()
            for item in payload.get("members") or []
            if str(item.get("symbol") or "").strip()
        }

    @staticmethod
    def _membership(
        symbol: str,
        membership_sets: dict[str, set[str]],
    ) -> dict[str, bool]:
        return {
            name: symbol in members
            for name, members in membership_sets.items()
        }

    @staticmethod
    def _belongs(row: dict[str, Any], universe: str) -> bool:
        membership = row.get("membership")
        return bool(
            isinstance(membership, dict)
            and membership.get(universe)
        )

    @classmethod
    def _normalize_universes(
        cls,
        values: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        raw = list(values or cls.UNIVERSES)
        output: list[str] = []
        for value in raw:
            name = normalize_index_name(value)
            if name not in output:
                output.append(name)
        if not output:
            raise ValueError("at least one universe is required")
        return output

    @classmethod
    def _normalize_modes(
        cls,
        values: list[str] | tuple[str, ...] | None,
    ) -> list[str]:
        raw = list(values or ("intraday", "swing"))
        output: list[str] = []
        for value in raw:
            mode = str(value or "").strip().lower()
            if mode not in cls.MODES:
                raise ValueError(
                    "modes must contain only intraday, swing or positional"
                )
            if mode not in output:
                output.append(mode)
        if not output:
            raise ValueError("at least one mode is required")
        return output

    def _mode_strategies(
        self,
        *,
        mode: str,
        source: str,
        strategy_ids: list[str] | None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        rows = self.strategy_engine.strategies(
            mode=mode,
            source=source,
            strategy_ids=None,
        )
        if strategy_ids:
            requested = {
                str(item).strip().lower()
                for item in strategy_ids
                if str(item).strip()
            }
            rows = [
                row for row in rows
                if row.get("strategy_id") in requested
            ]
        backtestable = set(
            self.backtester.readiness().get("backtestable_strategy_ids") or []
        )
        included: list[dict[str, Any]] = []
        excluded: list[dict[str, Any]] = []
        for row in rows:
            strategy_id = str(row.get("strategy_id") or "")
            reason = None
            if strategy_id in REVIEW_REQUIRED:
                reason = "review_required"
            elif strategy_id in CONFIRMATION_ONLY:
                reason = "confirmation_only"
            elif strategy_id not in backtestable:
                reason = "no_deterministic_backtest_evaluator"
            if reason:
                excluded.append(
                    {
                        "strategy_id": strategy_id,
                        "name": row.get("name"),
                        "mode": mode,
                        "reason": reason,
                    }
                )
            else:
                included.append(row)
        return included, excluded

    @classmethod
    def _gate(cls, row: dict[str, Any]) -> dict[str, Any]:
        policy = cls.VALIDATION_GATE
        completed = int(row.get("completed_symbols") or 0)
        trades = int(row.get("total_trades") or 0)
        scope_pct = cls._finite(row.get("universe_scope_pct"))
        if (
            completed < int(policy["minimum_completed_symbols"])
            or trades < int(policy["minimum_total_trades"])
            or scope_pct < float(policy["minimum_universe_scope_pct"])
        ):
            return {
                "status": "INSUFFICIENT_DATA",
                "passed": False,
                "checks": {
                    "minimum_completed_symbols": (
                        completed >= int(policy["minimum_completed_symbols"])
                    ),
                    "minimum_total_trades": (
                        trades >= int(policy["minimum_total_trades"])
                    ),
                    "minimum_universe_scope": (
                        scope_pct
                        >= float(policy["minimum_universe_scope_pct"])
                    ),
                },
            }

        pf = row.get("profit_factor")
        gross_profit = cls._finite(row.get("gross_profit"))
        gross_loss = cls._finite(row.get("gross_loss"))
        pf_ok = (
            cls._finite(pf, default=-1.0)
            >= float(policy["minimum_profit_factor"])
            if pf is not None
            else gross_profit > 0 and gross_loss == 0
        )
        checks = {
            "coverage": (
                cls._finite(row.get("coverage_pct"))
                >= float(policy["minimum_coverage_pct"])
            ),
            "positive_net_pnl": (
                cls._finite(row.get("net_pnl")) > 0
                if policy["require_positive_net_pnl"]
                else True
            ),
            "profitable_symbol_pct": (
                cls._finite(row.get("profitable_symbol_pct"))
                >= float(policy["minimum_profitable_symbol_pct"])
            ),
            "profit_factor": pf_ok,
            "median_symbol_return": (
                cls._finite(row.get("median_symbol_return_pct"))
                > float(
                    policy[
                        "minimum_median_symbol_return_pct_exclusive"
                    ]
                )
            ),
            "average_drawdown": (
                cls._finite(row.get("average_max_drawdown_pct"))
                <= float(policy["maximum_average_drawdown_pct"])
            ),
            "worst_drawdown": (
                cls._finite(row.get("worst_max_drawdown_pct"))
                <= float(policy["maximum_worst_drawdown_pct"])
            ),
        }
        passed = all(checks.values())
        return {
            "status": "PASS" if passed else "FAIL",
            "passed": passed,
            "checks": checks,
        }

    def _aggregate(
        self,
        *,
        universes: list[str],
        modes: list[str],
        strategy_rows: dict[str, list[dict[str, Any]]],
        tested_symbols: list[str],
        membership_sets: dict[str, set[str]],
        backtests: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        capital: float,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for universe in universes:
            requested_symbols = [
                symbol for symbol in tested_symbols
                if symbol in membership_sets[universe]
            ]
            for mode in modes:
                for strategy in strategy_rows.get(mode, []):
                    strategy_id = strategy["strategy_id"]
                    tests = [
                        row for row in backtests
                        if row.get("mode") == mode
                        and row.get("strategy_id") == strategy_id
                        and self._belongs(row, universe)
                    ]
                    completed_rows = [
                        row for row in tests
                        if row.get("status") == "completed"
                    ]
                    universe_trades = [
                        row for row in trades
                        if row.get("mode") == mode
                        and row.get("strategy_id") == strategy_id
                        and self._belongs(row, universe)
                    ]
                    returns = [
                        self._finite(row.get("return_pct"))
                        for row in completed_rows
                    ]
                    drawdowns = [
                        self._finite(row.get("max_drawdown_pct"))
                        for row in completed_rows
                    ]
                    net_pnl = sum(
                        self._finite(row.get("net_profit"))
                        for row in completed_rows
                    )
                    total_initial = len(completed_rows) * float(capital)
                    total_final = sum(
                        self._finite(row.get("final_capital"))
                        for row in completed_rows
                    )
                    profitable_symbols = len(
                        [
                            row for row in completed_rows
                            if self._finite(row.get("net_profit")) > 0
                        ]
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
                    wins = len(
                        [
                            row for row in universe_trades
                            if self._finite(row.get("net_pnl")) > 0
                        ]
                    )
                    row = {
                        "universe": universe,
                        "mode": mode,
                        "strategy_id": strategy_id,
                        "strategy_name": strategy.get("name"),
                        "source": strategy.get("source"),
                        "registry_paper_eligible": bool(
                            strategy.get("paper_eligible")
                        ),
                        "universe_total_symbols": len(
                            membership_sets[universe]
                        ),
                        "requested_symbols": len(requested_symbols),
                        "universe_scope_pct": round(
                            len(requested_symbols)
                            * 100.0
                            / max(1, len(membership_sets[universe])),
                            4,
                        ),
                        "completed_symbols": len(completed_rows),
                        "error_symbols": len(
                            [
                                item for item in tests
                                if item.get("status") == "error"
                            ]
                        ),
                        "coverage_pct": round(
                            len(completed_rows)
                            * 100.0
                            / max(1, len(requested_symbols)),
                            4,
                        ),
                        "independent_capital_per_symbol": round(
                            float(capital), 2
                        ),
                        "aggregate_test_capital": round(total_initial, 2),
                        "aggregate_final_capital": round(total_final, 2),
                        "net_pnl": round(net_pnl, 2),
                        "return_on_aggregate_test_capital_pct": round(
                            net_pnl * 100.0 / total_initial
                            if total_initial
                            else 0.0,
                            4,
                        ),
                        "average_symbol_return_pct": round(
                            sum(returns) / len(returns)
                            if returns else 0.0,
                            4,
                        ),
                        "median_symbol_return_pct": round(
                            median(returns) if returns else 0.0,
                            4,
                        ),
                        "profitable_symbols": profitable_symbols,
                        "loss_making_symbols": (
                            len(completed_rows) - profitable_symbols
                        ),
                        "profitable_symbol_pct": round(
                            profitable_symbols
                            * 100.0
                            / max(1, len(completed_rows)),
                            4,
                        ),
                        "symbols_with_trades": len(
                            {
                                str(item.get("symbol"))
                                for item in universe_trades
                            }
                        ),
                        "total_trades": len(universe_trades),
                        "trade_wins": wins,
                        "trade_losses": len(universe_trades) - wins,
                        "trade_win_rate_pct": round(
                            wins * 100.0 / len(universe_trades)
                            if universe_trades else 0.0,
                            4,
                        ),
                        "gross_profit": round(gross_profit, 2),
                        "gross_loss": round(gross_loss, 2),
                        "profit_factor": (
                            round(gross_profit / gross_loss, 4)
                            if gross_loss > 0
                            else None
                            if gross_profit > 0
                            else 0.0
                        ),
                        "trade_expectancy": round(
                            sum(
                                self._finite(item.get("net_pnl"))
                                for item in universe_trades
                            )
                            / len(universe_trades)
                            if universe_trades
                            else 0.0,
                            2,
                        ),
                        "average_max_drawdown_pct": round(
                            sum(drawdowns) / len(drawdowns)
                            if drawdowns else 0.0,
                            4,
                        ),
                        "worst_max_drawdown_pct": round(
                            max(drawdowns) if drawdowns else 0.0,
                            4,
                        ),
                        "average_sharpe_ratio": round(
                            sum(
                                self._finite(item.get("sharpe_ratio"))
                                for item in completed_rows
                            )
                            / len(completed_rows)
                            if completed_rows
                            else 0.0,
                            4,
                        ),
                        "transaction_costs": round(
                            sum(
                                self._finite(
                                    item.get("transaction_costs")
                                )
                                for item in completed_rows
                            ),
                            2,
                        ),
                        "slippage_impact_estimate": round(
                            sum(
                                self._finite(
                                    item.get(
                                        "slippage_impact_estimate"
                                    )
                                )
                                for item in completed_rows
                            ),
                            2,
                        ),
                    }
                    row["validation_gate"] = self._gate(row)
                    output.append(row)
        return output

    @staticmethod
    def _strategy_validation(
        *,
        universe_metrics: list[dict[str, Any]],
        universes: list[str],
    ) -> list[dict[str, Any]]:
        keys = sorted(
            {
                (
                    str(row.get("strategy_id")),
                    str(row.get("strategy_name")),
                    str(row.get("mode")),
                    str(row.get("source")),
                    bool(row.get("registry_paper_eligible")),
                )
                for row in universe_metrics
            }
        )
        output: list[dict[str, Any]] = []
        for (
            strategy_id,
            strategy_name,
            mode,
            source,
            paper_eligible,
        ) in keys:
            rows = [
                row for row in universe_metrics
                if row.get("strategy_id") == strategy_id
                and row.get("mode") == mode
            ]
            pass_count = sum(
                1 for row in rows
                if (row.get("validation_gate") or {}).get("status")
                == "PASS"
            )
            fail_count = sum(
                1 for row in rows
                if (row.get("validation_gate") or {}).get("status")
                == "FAIL"
            )
            insufficient_count = sum(
                1 for row in rows
                if (row.get("validation_gate") or {}).get("status")
                == "INSUFFICIENT_DATA"
            )
            expected = len(universes)
            eligible = bool(
                paper_eligible
                and pass_count == expected
                and fail_count == 0
                and insufficient_count == 0
            )
            status = (
                "ELIGIBLE_FOR_REVIEW"
                if eligible
                else "NOT_ELIGIBLE"
                if fail_count > 0
                else "INSUFFICIENT_DATA"
            )
            output.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_name": strategy_name,
                    "mode": mode,
                    "source": source,
                    "registry_paper_eligible": paper_eligible,
                    "universes_required": expected,
                    "universes_passed": pass_count,
                    "universes_failed": fail_count,
                    "universes_insufficient_data": insufficient_count,
                    "promotion_status": status,
                    "paper_execution_enabled": False,
                    "universe_gates": [
                        {
                            "universe": row.get("universe"),
                            "status": (
                                row.get("validation_gate") or {}
                            ).get("status"),
                        }
                        for row in rows
                    ],
                }
            )
        return output

    def _monthly_pnl(
        self,
        *,
        universes: list[str],
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        buckets: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for universe in universes:
            for trade in trades:
                if not self._belongs(trade, universe):
                    continue
                try:
                    month = pd.Timestamp(
                        trade.get("exit_at")
                    ).strftime("%Y-%m")
                except Exception:
                    month = "unknown"
                key = (
                    universe,
                    str(trade.get("mode")),
                    str(trade.get("strategy_id")),
                    month,
                )
                bucket = buckets.setdefault(
                    key,
                    {
                        "universe": universe,
                        "mode": str(trade.get("mode")),
                        "strategy_id": str(
                            trade.get("strategy_id")
                        ),
                        "strategy_name": trade.get("strategy_name"),
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
                bucket["gross_pnl"] += self._finite(
                    trade.get("gross_pnl")
                )
                bucket["transaction_costs"] += self._finite(
                    trade.get("transaction_costs")
                )
                bucket["net_pnl"] += net
        output: list[dict[str, Any]] = []
        for key in sorted(buckets):
            row = dict(buckets[key])
            for field in (
                "gross_pnl",
                "transaction_costs",
                "net_pnl",
            ):
                row[field] = round(float(row[field]), 2)
            output.append(row)
        return output

    def run(
        self,
        *,
        universes: list[str] | None = None,
        modes: list[str] | None = None,
        source: str = "all",
        strategy_ids: list[str] | None = None,
        capital: float = 100_000.0,
        chunk_size: int = 25,
        limit: int | None = None,
        force_refresh_universes: bool = False,
        run_id: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_id or "").strip() or (
            f"r7253-{uuid4().hex[:12]}"
        )
        capital = float(capital)
        if not math.isfinite(capital) or capital < 1_000:
            raise ValueError("capital must be at least 1000")
        chunk_size = max(1, min(50, int(chunk_size)))
        if limit is not None:
            limit = int(limit)
            if limit < 1 or limit > 500:
                raise ValueError("limit must be between 1 and 500")

        selected_universes = self._normalize_universes(universes)
        selected_modes = self._normalize_modes(modes)
        source_key = str(source or "all").strip().lower()
        if source_key not in {
            "all",
            "user_notebook",
            "template",
        }:
            raise ValueError(
                "source must be all, user_notebook or template"
            )

        universe_payloads = {
            name: self.universe_provider.load(
                name,
                force_refresh=force_refresh_universes,
            )
            for name in selected_universes
        }
        membership_sets = {
            name: self._members(payload)
            for name, payload in universe_payloads.items()
        }
        master_symbols = sorted(
            set().union(*membership_sets.values())
        )
        if limit is not None:
            master_symbols = master_symbols[:limit]
        if not master_symbols:
            raise RuntimeError("Selected universes contain no symbols")

        strategy_rows: dict[str, list[dict[str, Any]]] = {}
        excluded_strategies: list[dict[str, Any]] = []
        for mode in selected_modes:
            included, excluded = self._mode_strategies(
                mode=mode,
                source=source_key,
                strategy_ids=strategy_ids,
            )
            strategy_rows[mode] = included
            excluded_strategies.extend(excluded)
        if not any(strategy_rows.values()):
            raise ValueError(
                "No standalone executable strategies match the request"
            )

        started_at = self._timestamp()
        backtests: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        total_units = len(master_symbols) * len(selected_modes)
        completed_units = 0

        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        for mode in selected_modes:
            mode_strategies = strategy_rows.get(mode) or []
            if not mode_strategies:
                continue
            config = self.DEFAULT_ASSUMPTIONS[mode]
            mode_key, interval, period = self.scanner._mode_config(
                mode,
                str(config["period"]),
            )
            cost_bps = float(config["cost_bps"])
            slippage_bps = float(config["slippage_bps"])

            for batch_number, chunk in enumerate(
                self._chunks(master_symbols, chunk_size),
                start=1,
            ):
                if progress_callback is not None:
                    progress_callback(
                        {
                            "phase": "market_data",
                            "mode": mode_key,
                            "batch": batch_number,
                            "processed_symbol_modes": completed_units,
                            "total_symbol_modes": total_units,
                        }
                    )
                frames, failures = (
                    self.market_data.batch_candles_with_errors(
                        chunk,
                        period=period,
                        interval=interval,
                    )
                )
                for symbol in chunk:
                    membership = self._membership(
                        symbol,
                        membership_sets,
                    )
                    raw = frames.get(symbol)
                    if raw is None:
                        error = str(
                            failures.get(symbol)
                            or "Kite returned no historical candle data"
                        )
                        for strategy in mode_strategies:
                            backtests.append(
                                {
                                    "symbol": symbol,
                                    "mode": mode_key,
                                    "strategy_id": strategy["strategy_id"],
                                    "strategy_name": strategy.get("name"),
                                    "source": strategy.get("source"),
                                    "status": "error",
                                    "error": error,
                                    "membership": membership,
                                }
                            )
                        errors.append(
                            {
                                "symbol": symbol,
                                "mode": mode_key,
                                "phase": "market_data",
                                "batch": batch_number,
                                "error": error,
                                "membership": membership,
                            }
                        )
                        completed_units += 1
                        continue

                    try:
                        completed = self.scanner._completed_bars(
                            raw,
                            interval=interval,
                        )
                        if len(completed) < 120:
                            raise ValueError(
                                "At least 120 completed candles are required"
                            )
                        frame = self.indicators.calculate(
                            completed.copy()
                        )
                        if mode_key == "intraday":
                            frame = (
                                self.scanner._intraday_session_overrides(
                                    frame
                                )
                            )

                        for strategy in mode_strategies:
                            strategy_id = strategy["strategy_id"]
                            try:
                                simulation = self.backtester.run(
                                    frame,
                                    strategy_id=strategy_id,
                                    mode=mode_key,
                                    interval=interval,
                                    initial_capital=capital,
                                    cost_bps=cost_bps,
                                    slippage_bps=slippage_bps,
                                )
                                metrics = simulation.metrics
                                backtests.append(
                                    {
                                        "symbol": symbol,
                                        "mode": mode_key,
                                        "strategy_id": strategy_id,
                                        "strategy_name": strategy.get(
                                            "name"
                                        ),
                                        "source": strategy.get("source"),
                                        "status": "completed",
                                        "period": period,
                                        "interval": interval,
                                        "start_date": self.scanner._label(
                                            frame.index[0]
                                        ),
                                        "end_date": self.scanner._label(
                                            frame.index[-1]
                                        ),
                                        "bars": len(frame),
                                        **metrics,
                                        "membership": membership,
                                    }
                                )
                                for trade in simulation.trades:
                                    trades.append(
                                        {
                                            "symbol": symbol,
                                            "mode": mode_key,
                                            "strategy_id": strategy_id,
                                            "strategy_name": strategy.get(
                                                "name"
                                            ),
                                            "source": strategy.get("source"),
                                            "period": period,
                                            "interval": interval,
                                            **trade,
                                            "membership": membership,
                                        }
                                    )
                            except Exception as exc:
                                error = (
                                    f"{type(exc).__name__}: {exc}"
                                )
                                backtests.append(
                                    {
                                        "symbol": symbol,
                                        "mode": mode_key,
                                        "strategy_id": strategy_id,
                                        "strategy_name": strategy.get(
                                            "name"
                                        ),
                                        "source": strategy.get("source"),
                                        "status": "error",
                                        "error": error,
                                        "membership": membership,
                                    }
                                )
                                errors.append(
                                    {
                                        "symbol": symbol,
                                        "mode": mode_key,
                                        "strategy_id": strategy_id,
                                        "phase": "backtest",
                                        "batch": batch_number,
                                        "error": error,
                                        "membership": membership,
                                    }
                                )
                    except Exception as exc:
                        error = f"{type(exc).__name__}: {exc}"
                        for strategy in mode_strategies:
                            backtests.append(
                                {
                                    "symbol": symbol,
                                    "mode": mode_key,
                                    "strategy_id": strategy["strategy_id"],
                                    "strategy_name": strategy.get("name"),
                                    "source": strategy.get("source"),
                                    "status": "error",
                                    "error": error,
                                    "membership": membership,
                                }
                            )
                        errors.append(
                            {
                                "symbol": symbol,
                                "mode": mode_key,
                                "phase": "indicator_pipeline",
                                "batch": batch_number,
                                "error": error,
                                "membership": membership,
                            }
                        )
                    finally:
                        completed_units += 1
                        if progress_callback is not None:
                            progress_callback(
                                {
                                    "phase": "backtest",
                                    "mode": mode_key,
                                    "symbol": symbol,
                                    "batch": batch_number,
                                    "processed_symbol_modes": completed_units,
                                    "total_symbol_modes": total_units,
                                    "progress_pct": round(
                                        completed_units
                                        * 100.0
                                        / max(1, total_units),
                                        2,
                                    ),
                                }
                            )

        universe_metrics = self._aggregate(
            universes=selected_universes,
            modes=selected_modes,
            strategy_rows=strategy_rows,
            tested_symbols=master_symbols,
            membership_sets=membership_sets,
            backtests=backtests,
            trades=trades,
            capital=capital,
        )
        strategy_validation = self._strategy_validation(
            universe_metrics=universe_metrics,
            universes=selected_universes,
        )
        monthly_pnl = self._monthly_pnl(
            universes=selected_universes,
            trades=trades,
        )
        observation: dict[str, Any] = {}
        method = getattr(
            self.market_data,
            "observability_snapshot",
            None,
        )
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
            "universes": selected_universes,
            "modes": selected_modes,
            "source": source_key,
            "master_symbol_count": len(master_symbols),
            "strategy_count": len(
                {
                    row["strategy_id"]
                    for rows in strategy_rows.values()
                    for row in rows
                }
            ),
            "excluded_strategies": excluded_strategies,
            "assumptions": {
                "independent_capital_per_symbol": round(
                    capital, 2
                ),
                "aggregation_note": (
                    "Each symbol/strategy is backtested independently; "
                    "aggregate P/L is not a concurrent portfolio."
                ),
                "same_bar_priority": "stop",
                "intraday_forced_exit_ist": "15:00",
                "mode_settings": self.DEFAULT_ASSUMPTIONS,
                "validation_gate": self.VALIDATION_GATE,
            },
            "universe_metadata": {
                name: {
                    key: value
                    for key, value in payload.items()
                    if key != "members"
                }
                for name, payload in universe_payloads.items()
            },
            "strategy_universe_metrics": universe_metrics,
            "strategy_validation": strategy_validation,
            "backtest_results": backtests,
            "trades": trades,
            "monthly_pnl": monthly_pnl,
            "errors": errors,
            "provider_observation": observation,
            "safety": {
                "historical_backtest_only": True,
                "paper_execution_enabled": False,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
                "automatic_promotion": False,
                "promotion_requires_later_explicit_batch": True,
                "fundamentals_used": False,
                "enrichment_used": False,
            },
        }

    def readiness(self) -> dict[str, Any]:
        return {
            "status": "ready",
            "version": self.VERSION,
            "universes": list(self.UNIVERSES),
            "modes": list(self.MODES),
            "default_assumptions": self.DEFAULT_ASSUMPTIONS,
            "validation_gate": self.VALIDATION_GATE,
            "backtest_engine": self.backtester.readiness(),
            "execution": {
                "historical_backtest_only": True,
                "automatic_run": False,
                "paper_execution_enabled": False,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
                "automatic_promotion": False,
            },
        }


__all__ = ["MultiStrategyValidationService"]
