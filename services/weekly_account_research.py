"""Four controlled comparisons using the same observations and one account each."""

from uuid import uuid4

import pandas as pd

from backtest.weekly_account_engine import simulate_account
from scanner.weekly_account_policy import COMPARISONS, VERSION
from scanner.weekly_floor import STRATEGY_ID, daily_history, local_now
from services.research_report import build_report


class WeeklyAccountResearch:
    def __init__(self, original):
        self.original = original
        self.technical = original.technical

    def run(
        self,
        *,
        symbols,
        mode,
        period=None,
        now=None,
        run_id=None,
        progress=None,
        simulation_progress=None,
        max_candle_rows=None,
        report_horizon=None,
        report_stock_list=None,
        tick_size=0.05,
        cost_bps=12,
        slippage_bps=5,
    ):
        self.technical._number("tick_size", tick_size, minimum=0.00001, maximum=100)
        run_id = run_id or "weekly-comparison-" + uuid4().hex
        if self.technical.repository.by_run_id(run_id) is not None:
            raise ValueError("backtest run_id already exists")
        if cost_bps != 12 or slippage_bps != 5:
            raise ValueError("First comparison requires 12 bps fees and 5 bps slippage")
        requested, period, frames, weekly, annual, errors, coverage = (
            self.original._history(
                symbols,
                mode,
                period,
                now,
                progress,
                max_candle_rows,
                require_latest=False,
                full_daily=True,
            )
        )
        if not frames:
            raise ValueError("No valid per-stock history for the account comparison")
        cutoff = local_now(now) - pd.DateOffset(years=int(period[0]))
        benchmark, benchmark_error = None, None
        try:
            raw = self.technical.market_data.candles(
                "NIFTY 100", period="5y", interval="1d"
            )
            benchmark = daily_history(raw, now=now)
        except Exception:
            benchmark_error = "NIFTY_100_HISTORY_UNAVAILABLE"
        variants, comparisons = [], []
        previous = None
        for offset, policy in enumerate(COMPARISONS):

            def stage_progress(done, total, offset=offset):
                if simulation_progress:
                    simulation_progress(offset * total + done, len(COMPARISONS) * total)

            result = simulate_account(
                frames,
                weekly,
                annual,
                policy,
                tick_size=tick_size,
                start=cutoff,
                benchmark=benchmark,
                progress=stage_progress,
            )
            result["status"] = "completed"
            result["parameters"] = {
                **self.original.parameters(),
                "account_policy_version": VERSION,
                "account_policy": policy.to_dict(),
                "capital_basis": "current_equity",
            }
            from services.execution_report import validate_result

            validate_result(result)
            variants.append(result)
            metrics = result["metrics"]
            comparisons.append(
                {
                    "variant": policy.variant,
                    "order": offset + 1,
                    **metrics,
                    **{
                        f"change_{key}": metrics[key] - previous[key]
                        if previous is not None
                        and metrics[key] is not None
                        and previous[key] is not None
                        else None
                        for key in (
                            "net_profit",
                            "max_drawdown_pct",
                            "profit_factor",
                            "skipped_trades",
                        )
                    },
                }
            )
            previous = metrics
        result = dict(variants[-1])
        first, last = result["equity_curve"][0], result["equity_curve"][-1]
        if benchmark is not None:
            dates = pd.DatetimeIndex(
                [p["date"] for p in result["equity_curve"]]
            ).normalize()
            expected = dates + pd.Timedelta(hours=9, minutes=15)
            if not expected.isin(benchmark.index).all():
                benchmark_error = "NIFTY_100_BENCHMARK_PARTIAL_COVERAGE"
        benchmark_points = [
            p for p in result["equity_curve"] if p["benchmark_equity"] is not None
        ]
        benchmark_result = {
            "symbol": "NIFTY 100",
            "kind": "price_index_buy_and_hold_no_costs_no_dividends",
            "status": "complete"
            if benchmark_error is None
            else "unavailable"
            if not benchmark_points
            else "partial",
            "error_code": benchmark_error,
            "return_pct": (benchmark_points[-1]["benchmark_equity"] / 100000 - 1) * 100
            if benchmark_points
            else None,
            "max_drawdown_pct": None,
            "excess_return_pct": None,
        }
        if benchmark_points:
            from backtest.weekly_account_engine import drawdown

            benchmark_result["max_drawdown_pct"] = drawdown(
                [p["benchmark_equity"] for p in benchmark_points]
            )
        if benchmark_result["status"] == "complete":
            benchmark_result["excess_return_pct"] = (
                result["metrics"]["return_pct"] - benchmark_result["return_pct"]
            )
        for row in comparisons:
            row["benchmark_return_pct"] = benchmark_result["return_pct"]
            row["excess_return_pct"] = (
                row["return_pct"] - benchmark_result["return_pct"]
                if benchmark_result["status"] == "complete"
                else None
            )
        parameters = {
            **self.original.parameters(),
            "account_policy_version": VERSION,
            "capital_basis": "current_equity",
            "comparison_order": [p.variant for p in COMPARISONS],
            "account_policy": result["account_policy"],
            "research_settings_require_validation": True,
            "cost_bps": 12,
            "slippage_bps": 5,
            "tick_size_assumption": tick_size,
            "terminal_reporting": (
                "daily_MTM_before_terminal_costs; terminal_cash_bridge_separate"
            ),
            "batch_scope": "history_fetch_only_one_shared_account",
            "additional_gap_scenarios": "deferred_1pct_3pct_5pct",
            "index_trend_volume_trailing_time_filters": "deferred",
        }
        result.update(
            status="completed",
            run_id=run_id,
            strategy_id=STRATEGY_ID,
            symbol="PORTFOLIO",
            strategy={"name": "Weekly Floor shared-account comparison"},
            mode=mode,
            interval="1wk",
            period=period,
            symbols=sorted(frames),
            requested_symbols=requested,
            parameters=parameters,
            comparisons=comparisons,
            comparison_results=[
                {"variant": p.variant, **r}
                for p, r in zip(COMPARISONS, variants, strict=True)
            ],
            benchmark=benchmark_result,
            history_alignment={
                "method": "per_stock_history_union_calendar",
                "coverage": coverage,
                "history_errors": errors,
                "included_symbols": sorted(frames),
                "start_date": first["date"],
                "end_date": last["date"],
                "bars": len(result["equity_curve"]),
                "missing_session_policy": (
                    "carry_last_mark_with_stale_flag; never_invent_execution_candles"
                ),
            },
            created_at=self.technical._timestamp(),
            safety={
                "historical_simulation_only": True,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
            },
        )
        result["report"] = build_report(
            result,
            kind="backtest",
            horizon=report_horizon,
            stock_list=report_stock_list,
        )
        metrics = result["metrics"]
        self.technical.repository.save(
            {
                "run_id": run_id,
                "strategy_name": result["strategy"]["name"],
                "strategy_version": VERSION,
                "status": "completed",
                "symbol": "PORTFOLIO",
                "timeframe": "1wk",
                "start_date": result["start_date"],
                "end_date": result["end_date"],
                **{
                    k: metrics[k]
                    for k in (
                        "total_trades",
                        "win_rate",
                        "net_profit",
                        "initial_capital",
                        "final_capital",
                        "return_pct",
                        "profit_factor",
                    )
                },
                "max_drawdown": metrics["max_drawdown_pct"],
                "cost_bps": 12,
                "slippage_bps": 5,
                "parameters": parameters,
                "result": result,
                "created_at": result["created_at"],
            }
        )
        return result
