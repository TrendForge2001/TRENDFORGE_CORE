"""Kite-only shared-account historical simulations; no paper or broker writes."""

from __future__ import annotations

import re
from uuid import uuid4

from backtest.portfolio_engine import SharedPortfolioEngine
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
        slip = service._number("slippage_bps", slippage_bps, minimum=0, maximum=1000)
        run_id = str(run_id or f"portfolio-{uuid4().hex}")
        if service.repository.by_run_id(run_id) is not None:
            raise TechnicalTradingValidationError("backtest run_id already exists")
        begin = getattr(service.market_data, "begin_observation", None)
        if callable(begin):
            begin()
        frames, _failures = service.market_data.batch_candles_with_errors(
            requested,
            period=period,
            interval=profile.interval,
        )
        if any(s not in frames for s in requested):
            raise TechnicalTradingValidationError(
                "Portfolio history is incomplete; "
                "choose stocks with available Kite history"
            )
        enriched = {}
        for symbol in requested:
            completed = service._completed_bars(
                frames[symbol], interval=profile.interval, now=now
            )
            if len(completed) < 60:
                raise TechnicalTradingValidationError(
                    "Every stock needs at least 60 completed candles"
                )
            enriched[symbol] = service.indicators.calculate(completed.copy())
        try:
            aligned = engine.align(enriched)
            if len(next(iter(aligned.values()))) < 60:
                raise ValueError(
                    "Portfolio needs at least 60 aligned completed candles"
                )
            simulation = engine.run(
                aligned,
                strategy_id=strategy_id,
                mode=mode,
                interval=profile.interval,
                cost_bps=costs,
                slippage_bps=slip,
            )
        except ValueError as exc:
            raise TechnicalTradingValidationError(str(exc)) from None
        metrics = simulation["metrics"]
        result = {
            "status": "completed",
            "run_id": run_id,
            "symbol": "PORTFOLIO",
            "symbols": requested,
            "mode": mode,
            "period": period,
            "strategy_id": strategy_id,
            "strategy": definition,
            "interval": profile.interval,
            **simulation,
            "created_at": service._timestamp(),
            "engine": {"name": "SharedPortfolioEngine", "version": engine.VERSION},
            "parameters": {
                "initial_capital": 100000,
                "deployment_limit": 80000,
                "cash_reserve": 20000,
                "max_positions": 3,
                "allocation": "signal_score_proportional_integer_shares",
                "ranking": "score_desc_reward_risk_desc_symbol_asc",
                "cost_bps": costs,
                "slippage_bps": slip,
                "mode": mode,
                "same_bar_priority": "stop",
                "entry_fill": "next_bar_open",
                "reserve_reinvested": False,
                "profits_increase_deployment_limit": False,
            },
            "provider_observation": service._provider_observation(requested),
            "safety": {
                "historical_simulation_only": True,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
                "fundamentals_used": False,
            },
        }
        service.repository.save(
            {
                "run_id": run_id,
                "strategy_name": definition["name"],
                "strategy_version": engine.VERSION,
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
