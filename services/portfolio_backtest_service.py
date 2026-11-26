"""Kite-only shared-account historical simulations; no paper or broker writes."""

from __future__ import annotations

import re
from uuid import uuid4

import pandas as pd

from backtest.history_alignment import align_history
from backtest.portfolio_engine import SharedPortfolioEngine
from config.scanner_capacity import SCAN_BATCH_SIZE
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS, setup_indicators
from scanner.portfolio_policy import (
    ACCOUNT_CAPITAL,
    CASH_RESERVE,
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
)
from services.technical_trading_service import TechnicalTradingValidationError


class PortfolioBacktestService:
    def __init__(self, technical_service):
        self.technical = technical_service

    def run(
        self,
        *,
        symbols: list[str],
        mode: str,
        strategy_id: str,
        period: str | None = None,
        cost_bps: float = 12.0,
        slippage_bps: float = 5.0,
        run_id: str | None = None,
        now=None,
        liquidity_confirmation=False,
        tick_size=0.05,
        short_borrow_available=False,
        progress=None,
        simulation_progress=None,
        alignment_progress=None,
        report_horizon=None,
        report_stock_list=None,
        max_candle_rows=None,
        weekly_comparison=False,
        initial_capital=None,
        risk_fraction=None,
        max_positions=None,
        move_stop_after_partial=None,
    ) -> dict:
        from scanner.annual_exit_policy import AFFECTED
        from scanner.approved_strategies import (
            KEYS,
            active,
            context_for,
        )
        from scanner.approved_strategies import (
            VERSION as APPROVED_VERSION,
        )
        from scanner.vwma_yearly import STRATEGY_ID as VWMA_YEARLY_ID
        from scanner.weekly_floor import STRATEGY_ID as WEEKLY_FLOOR_ID

        approved = active(strategy_id)
        overrides = {
            key: value
            for key, value in {
                "initial_capital": initial_capital,
                "risk_fraction": risk_fraction,
                "max_positions": max_positions,
                "move_stop_after_partial": move_stop_after_partial,
            }.items()
            if value is not None
        }
        if overrides and not approved:
            raise TechnicalTradingValidationError(
                "Account overrides require an approved horizon strategy"
            )
        execution_cutoff = None
        if approved:
            from scanner.weekly_floor import local_now
            from services.research_history import cutoff, fetch_days
        approved_context = (
            context_for(strategy_id, mode, horizon=report_horizon) if approved else None
        )
        shared_annual = strategy_id in AFFECTED
        vwma_yearly = strategy_id == VWMA_YEARLY_ID

        if strategy_id == WEEKLY_FLOOR_ID:
            from services.weekly_floor_research import WeeklyFloorResearch

            try:
                return WeeklyFloorResearch(self.technical).backtest(
                    symbols=symbols,
                    mode=mode,
                    period=period,
                    run_id=run_id,
                    now=now,
                    cost_bps=cost_bps,
                    slippage_bps=slippage_bps,
                    progress=progress,
                    simulation_progress=simulation_progress,
                    report_horizon=report_horizon,
                    report_stock_list=report_stock_list,
                    max_candle_rows=max_candle_rows,
                    tick_size=tick_size,
                    comparison=weekly_comparison,
                )
            except ValueError as exc:
                raise TechnicalTradingValidationError(str(exc)) from None
        service = self.technical
        profile, period = service._period(mode, period)
        if approved:
            execution_cutoff = cutoff(local_now(now), period)
        requested = service._symbols(symbols)
        if any(
            not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", s) or ".." in s
            for s in requested
        ):
            raise TechnicalTradingValidationError("Invalid NSE stock symbol")
        engine = SharedPortfolioEngine()
        try:
            definition = engine.strategies.validate_strategy(strategy_id, mode=mode)
        except (ValueError, KeyError):
            raise TechnicalTradingValidationError(
                "Choose an executable source strategy"
            ) from None
        costs = service._number("cost_bps", cost_bps, minimum=0, maximum=1000)
        if (
            not shared_annual
            and strategy_id in EMA_PIVOT_SETUPS
            and EMA_PIVOT_SETUPS[strategy_id].direction == -1
            and not short_borrow_available
        ):
            raise TechnicalTradingValidationError(
                "Short research backtests require an explicit "
                "available-borrow assumption"
            )
        slip = service._number("slippage_bps", slippage_bps, minimum=0, maximum=1000)
        run_id = str(run_id or f"portfolio-{uuid4().hex}")
        if service.repository.by_run_id(run_id) is not None:
            raise TechnicalTradingValidationError("backtest run_id already exists")
        begin = getattr(service.market_data, "begin_observation", None)
        if callable(begin):
            begin()
        enriched = {}
        observed_rows = 0
        unavailable = []
        for offset in range(0, len(requested), SCAN_BATCH_SIZE):
            if progress:
                progress("history", offset)
            batch, _failures = service.market_data.batch_candles_with_errors(
                requested[offset : offset + SCAN_BATCH_SIZE],
                period=f"{fetch_days(local_now(now), period, profile.interval)}d"
                if approved
                else "5y"
                if vwma_yearly or (shared_annual and profile.interval == "1d")
                else period,
                interval=profile.interval,
            )
            batch = dict(batch)
            if progress:
                progress("history", min(offset + SCAN_BATCH_SIZE, len(requested)))
            for step, symbol in enumerate(
                requested[offset : offset + SCAN_BATCH_SIZE], 1
            ):
                try:
                    raw = batch.pop(symbol, None)
                    if raw is None:
                        raise ValueError("No history")
                    completed = service._completed_bars(
                        raw, interval=profile.interval, now=now
                    )
                    observed_rows += len(completed)
                    if max_candle_rows is not None and observed_rows > max_candle_rows:
                        from services.research_capacity import ResearchCapacityExceeded

                        raise ResearchCapacityExceeded(
                            "Observed history exceeds the worker candle budget"
                        )
                    if len(completed) < 60:
                        raise ValueError("Insufficient completed history")
                    if vwma_yearly:
                        from scanner.vwma_yearly import prepare_daily
                        from scanner.weekly_floor import local_now

                        frame = prepare_daily(completed, now=now)
                        cutoff = local_now(now) - pd.DateOffset(years=int(period[0]))
                        frame = frame.loc[frame.index >= cutoff]
                        if len(frame) < 60:
                            raise ValueError("Insufficient daily execution history")
                        if not frame["FIB_YEAR_P"].notna().any():
                            raise ValueError(
                                "Complete previous-year history is required"
                            )
                        required = {
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            *definition["indicators"],
                        }
                    else:
                        frame = service.indicators.calculate(completed.copy())
                        if shared_annual:
                            frame = (
                                service.yearly_references.enrich_approved
                                if approved
                                else service.yearly_references.enrich
                            )(
                                frame,
                                market_data=service.market_data,
                                symbol=symbol,
                                interval=profile.interval,
                                now=now,
                            )
                            observed_rows += frame.attrs.get("annual_reference_rows", 0)
                            if (
                                max_candle_rows is not None
                                and observed_rows > max_candle_rows
                            ):
                                from services.research_capacity import (
                                    ResearchCapacityExceeded,
                                )

                                raise ResearchCapacityExceeded(
                                    "Daily reference history exceeds "
                                    "the worker candle budget"
                                )
                            if profile.interval == "1d" and not approved:
                                from scanner.weekly_floor import local_now

                                cutoff = local_now(now) - pd.DateOffset(
                                    years=int(period[0])
                                )
                                frame = frame.loc[frame.index >= cutoff]
                            if (
                                not approved
                                or approved_context.horizon
                                in {"medium_term", "long_term"}
                            ) and not frame.FIB_YEAR_P.notna().any():
                                raise ValueError(
                                    "Complete prior-year history is required"
                                )
                    if not vwma_yearly and strategy_id in EMA_PIVOT_SETUPS:
                        required = {
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            *definition["indicators"],
                            *setup_indicators(EMA_PIVOT_SETUPS[strategy_id]),
                        }
                    elif not vwma_yearly:
                        from indicators.indicator_engine import IndicatorEngine

                        required = {
                            "open",
                            "high",
                            "low",
                            "close",
                            "volume",
                            *IndicatorEngine.REQUIRED_OUTPUTS,
                            *definition["indicators"],
                        }
                    if approved:
                        required = set(KEYS)
                        first = int(frame.index.searchsorted(execution_cutoff))
                        if len(frame) - first < 2:
                            raise ValueError("Insufficient observed execution history")
                        frame = frame.iloc[max(0, first - 2) :]
                    frame = frame[[key for key in frame if key in required]].copy()
                    enriched[symbol] = frame
                except (ValueError, TypeError, KeyError):
                    unavailable.append(
                        {
                            "symbol": symbol,
                            "reason": "history_unavailable_or_insufficient",
                        }
                    )
                if progress:
                    progress("indicators", offset + step)
        try:
            if alignment_progress:
                alignment_progress()
            aligned, alignment = align_history(enriched)
            alignment["excluded_symbols"].extend(unavailable)
            if progress:
                progress("simulation", len(requested))
            if vwma_yearly:
                from backtest.vwma_yearly_engine import VwmaYearlyBacktestEngine

                engine = VwmaYearlyBacktestEngine()
            simulation = engine.run(
                aligned,
                strategy_id=strategy_id,
                mode=mode,
                interval=profile.interval,
                cost_bps=costs,
                slippage_bps=slip,
                liquidity_confirmation=liquidity_confirmation,
                tick_size=tick_size,
                short_borrow_available=short_borrow_available,
                progress=simulation_progress,
                **(
                    {
                        "horizon": report_horizon,
                        "evaluation_start": execution_cutoff,
                        **overrides,
                    }
                    if approved
                    else {}
                ),
            )
        except ValueError as exc:
            raise TechnicalTradingValidationError(str(exc)) from None
        metrics = simulation["metrics"]
        result = {
            "status": "completed",
            "run_id": run_id,
            "symbol": "PORTFOLIO",
            "symbols": sorted(aligned),
            "requested_symbols": requested,
            "history_alignment": alignment,
            "mode": mode,
            "period": period,
            "strategy_id": strategy_id,
            "strategy": definition,
            "interval": profile.interval,
            **simulation,
            "created_at": service._timestamp(),
            "engine": {"name": "SharedPortfolioEngine", "version": engine.VERSION},
            "parameters": {
                "initial_capital": ACCOUNT_CAPITAL,
                "deployment_limit": DEPLOYMENT_LIMIT,
                "cash_reserve": CASH_RESERVE,
                "max_positions": MAX_POSITIONS,
                "allocation": "signal_score_proportional_integer_shares",
                "ranking": "score_desc_reward_risk_desc_symbol_asc",
                "cost_bps": costs,
                "slippage_bps": slip,
                "mode": mode,
                "same_bar_priority": "stop",
                "entry_fill": "next_bar_open",
                "reserve_reinvested": False,
                "profits_increase_deployment_limit": False,
                "short_accounting": "full_notional_collateral_no_proceeds_reuse",
            },
            "provider_observation": service._provider_observation(requested),
            "safety": {
                "historical_simulation_only": True,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
                "fundamentals_used": False,
            },
        }
        if not shared_annual and strategy_id in EMA_PIVOT_SETUPS:
            from backtest.ema_pivot_engine import EmaPivotBacktestEngine

            result["engine"] = {
                "name": "EmaPivotBacktestEngine",
                "version": EmaPivotBacktestEngine.VERSION,
            }
            result["parameters"].update(
                {
                    "entry_fill": "next_candle_only_strict_breakout_trigger",
                    "risk_fraction": 0.005,
                    "partial_exits": True,
                    "liquidity_confirmation": liquidity_confirmation,
                    "tick_size_assumption": tick_size,
                    "short_borrow_assumed": short_borrow_available,
                    "reserve_policy": "entry_budget_floor_losses_can_reduce_cash",
                    "ranking": "completed_signal_score_desc_symbol_asc",
                    "trailing_stop_updates": "completed_candle_next_bar_active",
                    "same_bar_priority": (
                        "active_stop_then_partial_then_breakeven_then_final"
                    ),
                    "event_timestamps": "candle_start_ist_intrabar_sequence_unknown",
                }
            )
        if vwma_yearly:
            from scanner.vwma_yearly import VERSION

            result["engine"] = {"name": "VwmaYearlyBacktestEngine", "version": VERSION}
            result["parameters"].update(
                {
                    "entry_fill": "next_session_open_plus_slippage",
                    "entry_gap_policy": (
                        "recompute_second_support_below_actual_fill_"
                        "reject_at_or_above_R1"
                    ),
                    "stop": (
                        "conditional_RSI_gap_OR_red_high_volume_close_below_second_support"
                    ),
                    "stop_is_resting_order": False,
                    "price_only_stop_exit": False,
                    "partial_exits": True,
                    "partial_target": "yearly_R1",
                    "partial_quantity": "floor_initial_quantity_divided_by_two",
                    "second_target": "yearly_R2_close_confirmation_else_next_open",
                    "final_target": "yearly_R3",
                    "trailing_reference": (
                        "raise_to_R1_R2_after_completed_high_volume_close"
                    ),
                    "annual_levels_frozen_at_entry": True,
                    "bearish_signal_action": "exit_existing_long_only",
                    "risk_fraction": 0.005,
                    "risk_basis": (
                        "planned_conditional_reference_not_guaranteed_maximum_loss"
                    ),
                    "volume_average": "SMA20_including_signal_session",
                    "volume_multiplier": 1.0,
                    "pivot_type": "Fibonacci",
                    "pivot_timeframe": "previous_calendar_year",
                    "pivot_display_sets": 20,
                    "rsi_range": {"above": 50, "through": 70, "preferred_through": 65},
                    "history_fetch_period": "5y",
                    "tick_size_assumption": tick_size,
                    "event_timestamps": (
                        "daily_session_start_IST_intrabar_sequence_unknown"
                    ),
                    "same_bar_priority": (
                        "known_open_exits_then_R1_partial_then_R3_limit_then_close_signals"
                    ),
                    "ranking": "completed_signal_score_desc_symbol_asc",
                }
            )
        if shared_annual:
            from scanner.annual_exit_policy import VERSION

            result["engine"] = {"name": "AnnualExitBacktestEngine", "version": VERSION}
            result["parameters"].update(
                {
                    "exit_policy_version": VERSION,
                    "entry_fill": "next_candle_only_breakout_trigger"
                    if strategy_id in EMA_PIVOT_SETUPS
                    else "next_candle_open_plus_slippage",
                    "stop": (
                        "RSI14_below30_AND_gap_down_OR_"
                        "red_high_volume_close_below_reference"
                    ),
                    "stop_is_resting_order": False,
                    "price_only_stop_exit": False,
                    "conditional_support": (
                        "second_distinct_yearly_pivot_below_actual_fill"
                    ),
                    "partial_exits": True,
                    "partial_target": "yearly_R1",
                    "partial_quantity": "floor_initial_quantity_divided_by_two",
                    "second_target": "yearly_R2_close_confirmation_else_next_open",
                    "final_target": "yearly_R3",
                    "annual_levels_frozen_at_entry": True,
                    "trailing_reference": (
                        "raise_to_R1_R2_after_completed_high_volume_close"
                    ),
                    "bearish_signal_action": "exit_existing_long_only",
                    "short_borrow_assumed": False,
                    "risk_fraction": 0.005,
                    "risk_basis": "conditional_reference_not_guaranteed_maximum_loss",
                    "exit_confirmation_interval": profile.interval,
                    "square_off_ist": "15:00" if mode == "intraday" else None,
                    "daily_reference_history": "5y",
                    "same_bar_priority": (
                        "known_open_exits_then_R1_partial_"
                        "then_R3_limit_then_close_signals"
                    ),
                    "liquidity_confirmation": liquidity_confirmation,
                    "tick_size_assumption": tick_size,
                }
            )
        if approved:
            result["engine"] = {
                "name": "ApprovedStrategyBacktestEngine",
                "version": APPROVED_VERSION,
            }
            result["parameters"].update(
                {
                    "exit_policy_version": APPROVED_VERSION,
                    "horizon": approved_context.horizon,
                    "entry_fill": (
                        "next_native_candle_open_with_actual_fill_revalidation"
                    ),
                    "exit_confirmation_interval": profile.interval,
                    "risk_fraction": 0.005,
                    "risk_basis": "conditional_reference_unless_explicit_hard_stop",
                    "partial_exits": approved_context.horizon
                    in {"medium_term", "long_term"},
                    "square_off_ist": "15:00" if mode == "intraday" else None,
                    "short_borrow_assumed": short_borrow_available,
                    "tick_size_assumption": tick_size,
                    "cost_bps": costs,
                    "slippage_bps": slip,
                    "same_bar_priority": (
                        "known_open_exits_then_hard_stop_"
                        "then_profit_limit_then_close_signals"
                    ),
                    "rules_document": "docs/APPROVED_HORIZON_STRATEGIES.md",
                }
            )
        from services.research_report import build_report

        if progress:
            progress("report", len(requested))
        result["parameters"].update(overrides)
        if overrides:
            from scanner.strategy_registry import REGISTRY_VERSION

            result["registry_version"] = REGISTRY_VERSION
        if initial_capital is not None:
            result["parameters"]["deployment_limit"] = initial_capital
        result["report"] = build_report(
            result,
            kind="backtest",
            horizon=report_horizon,
            stock_list=report_stock_list,
            historical=bool(overrides),
        )
        service.repository.save(
            {
                "run_id": run_id,
                "strategy_name": definition["name"],
                "strategy_version": result["engine"]["version"],
                "status": "completed",
                "symbol": "PORTFOLIO",
                "timeframe": profile.interval,
                "start_date": result["start_date"],
                "end_date": result["end_date"],
                "total_trades": metrics["total_trades"],
                "win_rate": metrics["win_rate"],
                "net_profit": metrics["net_profit"],
                "max_drawdown": metrics["max_drawdown_pct"],
                "initial_capital": metrics["initial_capital"],
                "final_capital": metrics["final_capital"],
                "return_pct": metrics["return_pct"],
                "profit_factor": metrics["profit_factor"],
                "cost_bps": costs,
                "slippage_bps": slip,
                "parameters": result["parameters"],
                "result": result,
                "created_at": result["created_at"],
            }
        )
        return result
