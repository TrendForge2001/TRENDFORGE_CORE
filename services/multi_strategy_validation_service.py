"""R72.5.3 multi-strategy backtest and validation service."""
from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime
from itertools import islice
from statistics import median
from typing import Any
from uuid import uuid4

import pandas as pd

from backtest.multi_strategy_backtest_engine import MultiStrategyBacktestEngine
from providers.nse_broad_market_constituents import normalize_index_name
from scanner.approved_strategies import active as approved_active
from scanner.approved_strategies import exit_only as approved_exit_only
from scanner.multi_strategy_engine import CONFIRMATION_ONLY, requires_review
from scanner.strategy_registry import REGISTRY_VERSION

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
        return datetime.now(UTC).isoformat()

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
            if requires_review(strategy_id):
                reason = "review_required"
            elif strategy_id in CONFIRMATION_ONLY:
                reason = "confirmation_only"
            elif approved_active(strategy_id) and approved_exit_only(strategy_id, mode):
                reason = "exit_only_for_horizon"
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
                    trade_count, wins = 0, 0
                    gross_profit, gross_loss, trade_net = 0.0, 0.0, 0.0
                    traded_symbols = set()
                    for trade in trades:
                        if trade.get("mode") != mode or trade.get("strategy_id") != strategy_id or not self._belongs(trade, universe):
                            continue
                        net = self._finite(trade.get("net_pnl"))
                        trade_count += 1
                        wins += int(net > 0)
                        gross_profit += max(0.0, net)
                        gross_loss -= min(0.0, net)
                        trade_net += net
                        traded_symbols.add(str(trade.get("symbol")))
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
                    losing_symbols = sum(self._finite(item.get("net_profit")) < 0 for item in completed_rows)
                    active_rows = [item for item in completed_rows if self._finite(item.get("total_trades")) > 0 or self._finite(item.get("net_profit")) != 0]
                    flat_symbols = sum(self._finite(item.get("net_profit")) == 0 for item in active_rows)
                    policy_hashes = {item.get("admission_policy_hash") for item in completed_rows}
                    aligned = len(policy_hashes) == 1 and None not in policy_hashes and bool(policy_hashes)
                    row = {
                        "universe": universe,
                        "mode": mode,
                        "strategy_id": strategy_id,
                        "strategy_name": strategy.get("name"),
                        "source": strategy.get("source"),
                        "registry_paper_eligible": bool(
                            strategy.get("paper_eligible")
                        ) and (not approved_active(strategy_id) or aligned),
                        "admission_policy_hash": next(iter(policy_hashes)) if aligned else None,
                        "validation_basis": "paper_policy_independent_stock" if aligned else "native_independent_stock_research",
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
                        "loss_making_symbols": losing_symbols,
                        "flat_traded_symbols": flat_symbols,
                        "no_trade_symbols": len(completed_rows) - len(active_rows),
                        "active_profitable_symbol_pct": round(profitable_symbols * 100 / len(active_rows), 4) if active_rows else None,
                        "active_median_symbol_return_pct": round(median([self._finite(item.get("return_pct")) for item in active_rows]), 4) if active_rows else None,
                        "admission_rejection_counts": {reason: sum(int(item.get("rejection_counts", {}).get(reason, 0)) for item in completed_rows) for reason in sorted({reason for item in completed_rows for reason in item.get("rejection_counts", {})})},
                        "admission_rejection_samples": list(islice((
                            {**sample, "symbol": item["symbol"]}
                            for item in completed_rows
                            for sample in item.get("rejection_samples", [])
                        ), 50)),
                        "profitable_symbol_pct": round(
                            profitable_symbols
                            * 100.0
                            / max(1, len(completed_rows)),
                            4,
                        ),
                        "symbols_with_trades": len(traded_symbols),
                        "total_trades": trade_count,
                        "trade_wins": wins,
                        "trade_losses": trade_count - wins,
                        "trade_win_rate_pct": round(
                            wins * 100.0 / trade_count
                            if trade_count else 0.0,
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
                        "trade_expectancy": round(trade_net / trade_count if trade_count else 0.0, 2),
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
                    "admission_policy_hash": rows[0].get("admission_policy_hash") if rows and all(row.get("admission_policy_hash") == rows[0].get("admission_policy_hash") for row in rows) else None,
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
                legs = trade.get("exit_legs") or [trade]
                position_net = self._finite(trade.get("net_pnl"))
                for offset, leg in enumerate(legs):
                    try:
                        month = pd.Timestamp(
                            leg.get("exit_at")
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
                            "exit_fills": 0,
                            "count_basis": "completed_positions_with_exit_fills_separate",
                            "wins": 0,
                            "losses": 0,
                            "gross_pnl": 0.0,
                            "transaction_costs": 0.0,
                            "net_pnl": 0.0,
                        },
                    )
                    net = self._finite(leg.get("net_pnl"))
                    bucket["trades"] += int(offset == len(legs) - 1)
                    bucket["exit_fills"] += 1
                    bucket["wins"] += int(offset == len(legs) - 1 and position_net > 0)
                    bucket["losses"] += int(offset == len(legs) - 1 and position_net <= 0)
                    bucket["gross_pnl"] += self._finite(
                        leg.get("gross_pnl")
                    )
                    bucket["transaction_costs"] += self._finite(
                        leg.get("transaction_costs")
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
        checkpoint=None,
        admission_policy=None,
        shared_book=False,
        assume_short_borrow=False,
        evaluation_as_of=None,
    ) -> dict[str, Any]:
        run_id = str(run_id or "").strip() or (
            f"r7253-{uuid4().hex[:12]}"
        )
        capital = float(capital)
        from services.paper_admission_policy import fingerprint
        from services.paper_admission_policy import validate as validate_policy

        policy = validate_policy(admission_policy) if admission_policy is not None else None
        if policy and (checkpoint is None or capital != policy["capital"]):
            raise ValueError("Corrected research requires a matching frozen policy and durable checkpoint")
        if not math.isfinite(capital) or capital < 1_000:
            raise ValueError("capital must be at least 1000")
        from core.deployment_role import on_render

        # One validation worker already runs at a time. Bound its resident
        # candle batch on the 512 MB service as well as its concurrency.
        chunk_size = max(1, min(5 if on_render() else 50, int(chunk_size)))
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
            "user_analysis",
            "template",
        }:
            raise ValueError(
                "source must be all, user_notebook, user_analysis or template"
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

        from services.validation_journal import compact_trade

        if checkpoint is not None:
            checkpoint.bind_universe(master_symbols, membership_sets)
        as_of = pd.Timestamp(checkpoint.metadata["as_of"]) if checkpoint else None
        replay = None
        if policy:
            from services.replay_store import ReplayStore

            replay = ReplayStore(checkpoint)
        started_at = checkpoint.metadata["as_of"] if checkpoint else self._timestamp()
        backtests = checkpoint.rows["backtests"] if checkpoint else []
        trades = checkpoint.rows["trades"] if checkpoint else []
        errors = checkpoint.rows["errors"] if checkpoint else []
        completed_keys = checkpoint.completed() if checkpoint else set()
        total_units = len(master_symbols) * len(selected_modes)
        completed_units = len(completed_keys)

        begin = getattr(self.market_data, "begin_observation", None)
        if callable(begin):
            begin()

        for mode in selected_modes:
            mode_strategies = strategy_rows.get(mode) or []
            from scanner.annual_exit_policy import AFFECTED

            annual_required = any(s["strategy_id"] in AFFECTED for s in mode_strategies)
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
                chunk = [symbol for symbol in chunk if (mode_key, symbol) not in completed_keys]
                if not chunk:
                    continue
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
                fetch_period = "5y" if annual_required and interval == "1d" else period
                cached = {}
                if policy:
                    from services.research_history import fetch_days

                    fetch_period = f"{fetch_days(as_of, '5y' if interval == '1d' else period, interval)}d"
                    if interval == "1d":
                        cached = {symbol: replay.load("seed_day", symbol) for symbol in chunk}
                        cached = {symbol: value for symbol, value in cached.items() if value is not None}
                if checkpoint:
                    # Overfetch elapsed days, then apply the original cutoff to
                    # preserve the EMA seed and exclude candles after the request.
                    days = int(fetch_period[:-1]) if fetch_period.endswith("d") else int(fetch_period[0])*366
                    elapsed = max(0, math.ceil((pd.Timestamp.now(tz="UTC")-as_of).total_seconds()/86400))
                    fetch_period = f"{days+elapsed}d"
                uncached = [symbol for symbol in chunk if symbol not in cached]
                frames, failures = (
                    self.market_data.batch_candles_with_errors(
                        uncached,
                        period=fetch_period,
                        interval=interval,
                    ) if uncached else ({}, {})
                )
                frames.update(cached)
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
                        if checkpoint:
                            checkpoint.commit_unit(mode_key, symbol)
                        completed_units += 1
                        if progress_callback:
                            progress_callback(dict(phase="backtest", mode=mode_key, processed_symbol_modes=completed_units,
                                                   total_symbol_modes=total_units, progress_pct=round(completed_units*100/max(1,total_units),2),
                                                   error_count=len(errors), trade_count=len(trades)))
                        continue

                    fatal_error = False
                    try:
                        completed = self.scanner._completed_bars(
                            raw,
                            interval=interval,
                            **({"now": as_of.to_pydatetime()} if checkpoint else {}),
                        )
                        if checkpoint:
                            start = as_of.tz_convert("Asia/Kolkata").normalize()-pd.Timedelta(days=days)
                            completed = completed.loc[completed.index >= start]
                        if len(completed) < 120:
                            raise ValueError(
                                "At least 120 completed candles are required"
                            )
                        if policy and interval == "1d" and symbol not in cached:
                            replay.save("seed_day", symbol, completed)
                        frame = self.indicators.calculate(
                            completed.copy()
                        )
                        if mode_key == "intraday":
                            frame = (
                                self.scanner._intraday_session_overrides(
                                    frame
                                )
                            )

                        from scanner.annual_exit_policy import AFFECTED

                        if any(s["strategy_id"] in AFFECTED for s in mode_strategies):
                            from scanner.approved_strategies import active

                            enrich = self.scanner.yearly_references.enrich_approved if any(active(s["strategy_id"]) for s in mode_strategies) else self.scanner.yearly_references.enrich
                            frame = enrich(
                                frame, market_data=self.market_data, symbol=symbol,
                                interval=interval,
                                **({"now": as_of.to_pydatetime()} if checkpoint else {}),
                            )
                            if interval == "1d" and not policy:
                                from scanner.weekly_floor import local_now

                                frame = frame.loc[frame.index >= local_now(as_of) - pd.DateOffset(years=int(period[0]))]

                        signal_context, execution_sessions, execution_start = None, None, None
                        if policy:
                            from services.aligned_signals import signals
                            from services.research_history import cutoff, entry_sessions

                            execution_start = cutoff(as_of, period)
                            offset = int(frame.index.searchsorted(execution_start))
                            frame = frame.iloc[max(0, offset - 2):]
                            signal_context = signals(frame, mode_key)
                            common_start = cutoff(as_of, "60d")
                            common_offset = int(frame.index.searchsorted(common_start))
                            from scanner.approved_strategies import KEYS

                            replay_frame = frame.iloc[max(0, common_offset - 3):]
                            replay.save("native_intra" if interval == "15m" else "native_day", symbol, replay_frame[[key for key in KEYS if key in replay_frame]])
                            if interval == "15m":
                                replay.save("quotes", symbol, frame.iloc[max(0, common_offset - 3):][["open", "high", "low", "close"]])
                            replay.save_signals(mode_key, symbol, signal_context, common_start - pd.Timedelta(days=7), frame)
                            if interval == "1d":
                                execution_sessions = replay.load("entry_sessions", symbol)
                                if execution_sessions is None:
                                    execution_frames, _ = self.market_data.batch_candles_with_errors([symbol], period=f"{5*366 + max(0, math.ceil((pd.Timestamp.now(tz='UTC')-as_of).total_seconds()/86400))}d", interval="15m")
                                    if symbol not in execution_frames:
                                        raise ValueError("Observed daily execution quotes unavailable")
                                    observed = self.scanner._completed_bars(execution_frames[symbol], interval="15m", now=as_of.to_pydatetime())
                                    execution_sessions = entry_sessions(observed)
                                    replay.save("entry_sessions", symbol, execution_sessions)

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
                                    **({"short_borrow_available": assume_short_borrow if policy else True} if strategy.get("family") in {"ema_pivot_research", "approved_horizon_rules"} else {}),
                                    **({"admission_policy": policy, "signal_context": signal_context, "execution_sessions": execution_sessions, "evaluation_start": execution_start} if policy else {}),
                                )
                                metrics = simulation.metrics
                                for sample in metrics.get("rejection_samples", []):
                                    sample["symbol"] = symbol
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
                                            frame.loc[frame.index >= execution_start].index[0] if policy else frame.index[0]
                                        ),
                                        "end_date": self.scanner._label(
                                            frame.index[-1]
                                        ),
                                        "bars": int(sum(frame.index >= execution_start)) if policy else len(frame),
                                        **metrics,
                                        "membership": membership,
                                    }
                                )
                                for trade in simulation.trades:
                                    trades.append(
                                        {
                                            "mode": mode_key,
                                            "strategy_id": strategy_id,
                                            "strategy_name": strategy.get(
                                                "name"
                                            ),
                                            "source": strategy.get("source"),
                                            "period": period,
                                            "interval": interval,
                                            **compact_trade(trade, strategy.get("indicators", ())),
                                            "symbol": symbol,
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
                        from services.replay_store import ReplayStorageFull

                        if isinstance(exc, ReplayStorageFull):
                            fatal_error = True
                            replay.close()
                            raise
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
                        discard = getattr(getattr(self.scanner, "yearly_references", None), "discard", None)
                        if callable(discard):
                            discard(symbol)
                        if checkpoint and not fatal_error:
                            checkpoint.commit_unit(mode_key, symbol)
                        if not fatal_error:
                            completed_units += 1
                        if progress_callback is not None and not fatal_error:
                            progress_callback(
                                {
                                    "phase": "backtest",
                                    "mode": mode_key,
                                    "symbol": symbol,
                                    "batch": batch_number,
                                    "processed_symbol_modes": completed_units,
                                    "total_symbol_modes": total_units,
                                    "error_count": len(errors),
                                    "trade_count": len(trades),
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

        shared_result = None
        if policy and shared_book:
            from backtest.aligned_paper_book import run_shared_book

            universe_order = list(dict.fromkeys(str(member["symbol"]).strip().upper() for payload in universe_payloads.values() for member in payload.get("members", []) if str(member.get("symbol", "")).strip().upper() in master_symbols))
            try:
                shared_result = run_shared_book(replay, symbols=universe_order, policy=policy, as_of=as_of, assume_short_borrow=assume_short_borrow, progress=progress_callback)
            finally:
                replay.close()
        elif replay:
            replay.close()
        completed_at = self._timestamp()
        return {
            "status": "completed",
            "version": self.VERSION,
            "run_id": run_id,
            "started_at": started_at,
            "as_of": as_of.isoformat() if checkpoint else None,
            "checkpointed": checkpoint is not None,
            "trade_evidence": "economic_fills_and_strategy_indicators_without_duplicate_plan_state",
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
                "ema_pivot_execution": {"partial_exits": True, "trailing_stops": True, "risk_fraction": policy["risk_per_trade_percent"] / 100 if policy else 0.005, "short_borrow_assumed_for_historical_simulation": assume_short_borrow if policy else True},
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
            "registry_version": REGISTRY_VERSION,
            "strategy_validation": strategy_validation,
            "admission_policy": policy,
            "admission_policy_hash": fingerprint(policy) if policy else None,
            "cost_model_basis": "explicit research estimates; fixed 2026 DP estimate, not a historical tax schedule" if policy else "legacy_percentage_assumptions",
            "shared_book": shared_result,
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
