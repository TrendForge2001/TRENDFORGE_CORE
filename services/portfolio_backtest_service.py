"""Kite-only shared-account historical simulations; no paper or broker writes."""

from __future__ import annotations

import re
from uuid import uuid4

from backtest.history_alignment import align_history
from backtest.portfolio_engine import SharedPortfolioEngine
from config.scanner_capacity import SCAN_BATCH_SIZE
from scanner.ema_pivot_setups import EMA_PIVOT_SETUPS
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
        report_horizon=None,
        report_stock_list=None,
    ) -> dict:
        service = self.technical
        profile, period = service._period(mode, period)
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
            strategy_id in EMA_PIVOT_SETUPS
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
        frames = {}
        for offset in range(0, len(requested), SCAN_BATCH_SIZE):
            batch, _failures = service.market_data.batch_candles_with_errors(
                requested[offset : offset + SCAN_BATCH_SIZE],
                period=period,
                interval=profile.interval,
            )
            frames.update(batch)
            if progress:
                progress("history", min(offset + SCAN_BATCH_SIZE, len(requested)))
        enriched = {}
        unavailable = []
        for symbol in requested:
            try:
                raw = frames.pop(symbol, None)
                if raw is None:
                    raise ValueError("No history")
                completed = service._completed_bars(
                    raw, interval=profile.interval, now=now
                )
                if len(completed) < 60:
                    raise ValueError("Insufficient completed history")
                enriched[symbol] = service.indicators.calculate(completed.copy())
            except (ValueError, TypeError, KeyError):
                unavailable.append(
                    {"symbol": symbol, "reason": "history_unavailable_or_insufficient"}
                )
        try:
            aligned, alignment = align_history(enriched)
            alignment["excluded_symbols"].extend(unavailable)
            if progress:
                progress("simulation", len(requested))
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
        if strategy_id in EMA_PIVOT_SETUPS:
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
        from services.research_report import build_report

        if progress:
            progress("report", len(requested))
        result["report"] = build_report(
            result,
            kind="backtest",
            horizon=report_horizon,
            stock_list=report_stock_list,
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
