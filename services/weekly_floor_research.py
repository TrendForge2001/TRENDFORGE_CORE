"""Kite daily-history adapter for the owner's weekly research strategy."""

import re
from uuid import uuid4

import pandas as pd

from backtest.history_alignment import align_history
from backtest.weekly_floor_engine import simulate_weekly
from config.scanner_capacity import SCAN_BATCH_SIZE
from scanner.portfolio_policy import (
    ACCOUNT_CAPITAL,
    CASH_RESERVE,
    DEPLOYMENT_LIMIT,
    MAX_POSITIONS,
    number,
)
from scanner.weekly_floor import (
    STRATEGY_ID,
    VERSION,
    daily_history,
    local_now,
    weekly_indicators,
    weekly_signal,
)
from services.scanner_data_health import detail
from services.stock_report_evidence import capture as capture_report_evidence


class WeeklyFloorResearch:
    def __init__(self, technical):
        self.technical = technical

    def _history(
        self,
        symbols,
        mode,
        period,
        now,
        progress,
        limit,
        *,
        require_latest=True,
        full_daily=False,
        sink=None,
    ):
        now = local_now(now)
        if mode != "positional":
            raise ValueError(
                "Weekly Floor recovery belongs to Long Term / positional research"
            )
        _, period = self.technical._period(mode, period)
        requested = self.technical._symbols(symbols)
        if any(
            not re.fullmatch(r"[A-Z0-9][A-Z0-9._&-]{0,29}", symbol) or ".." in symbol
            for symbol in requested
        ):
            raise ValueError("Invalid NSE stock symbol")
        frames, weekly, annual, errors, coverage = {}, {}, {}, [], []
        observed = 0
        for offset in range(0, len(requested), SCAN_BATCH_SIZE):
            chunk = requested[offset : offset + SCAN_BATCH_SIZE]
            chunk_observed = 0
            from services.candle_batches import fetch_candle_batch
            from services.scanner_data_health import DataNotReady, provider_detail

            raw, fetch_failures = fetch_candle_batch(
                self.technical.market_data, chunk, period="5y", interval="1d"
            )
            for symbol in chunk:
                daily_bars = 0
                completed_weeks, consecutive_weeks = None, None
                try:
                    if raw.get(symbol) is None:
                        raise DataNotReady(
                            provider_detail(fetch_failures.get(symbol))["data_code"]
                        )
                    daily = daily_history(raw.get(symbol), now=now)
                    daily_bars = len(daily)
                    observed += len(daily)
                    chunk_observed += len(daily)
                    from services.research_capacity import CLOUD_BATCH_CANDLE_ROWS

                    if sink is not None and chunk_observed > CLOUD_BATCH_CANDLE_ROWS:
                        from services.research_capacity import ResearchCapacityExceeded

                        raise ResearchCapacityExceeded(
                            "Fetch chunk exceeds the worker candle budget"
                        )
                    if limit is not None and observed > limit:
                        from services.research_capacity import ResearchCapacityExceeded

                        raise ResearchCapacityExceeded(
                            "Observed history exceeds the worker candle budget"
                        )
                    weeks, pivots = weekly_indicators(daily, now=now)
                    completed_weeks = len(weeks)
                    consecutive_weeks = int(weeks["WEEKLY_WARMUP"].iloc[-1])
                    if require_latest:
                        if consecutive_weeks < 100:
                            span = (weeks.index[-1] - weeks.index[0]).days // 7 + 1
                            raise DataNotReady(
                                "WEEKLY_HISTORY_GAPS"
                                if span >= 100
                                else "WEEKLY_WARMUP_NOT_READY"
                            )
                        if not pivots.get(local_now(now).year):
                            raise DataNotReady("ANNUAL_REFERENCE_MISSING")
                        weekly_signal(
                            weeks.iloc[-1], pivots=pivots.get(local_now(now).year, {})
                        )
                    cutoff = local_now(now) - pd.DateOffset(years=int(period[0]))
                    selected = daily.loc[daily.index >= cutoff]
                    if selected.empty or (require_latest and len(selected) < 60):
                        raise ValueError(
                            "Insufficient daily execution history in requested period"
                        )
                    execution = daily if full_daily else selected
                    if sink is None:
                        frames[symbol], weekly[symbol], annual[symbol] = (
                            execution,
                            weeks,
                            pivots,
                        )
                    else:
                        sink.add(symbol, execution, weeks, pivots)
                        frames[symbol] = None
                    coverage.append(
                        {
                            "symbol": symbol,
                            "observed_daily_bars": len(daily),
                            "completed_weekly_bars": len(weeks),
                            "history_start": daily.index[0].isoformat(),
                            "history_end": daily.index[-1].isoformat(),
                            "first_indicator_ready_week": (
                                weeks.loc[weeks.WEEKLY_WARMUP >= 100]
                                .index[0]
                                .isoformat()
                                if (weeks.WEEKLY_WARMUP >= 100).any()
                                else None
                            ),
                        }
                    )
                except (ValueError, TypeError, KeyError) as exc:
                    diagnosis = (
                        exc.public
                        if isinstance(exc, DataNotReady)
                        else detail("CANDLE_HISTORY_INVALID")
                    )
                    errors.append(
                        {
                            "symbol": symbol,
                            "reason": diagnosis["data_reason"],
                            **diagnosis,
                            "observed_daily_bars": daily_bars,
                            "completed_weekly_bars": completed_weeks,
                            "consecutive_completed_weeks": consecutive_weeks,
                            "required_completed_weeks": 100,
                        }
                    )
                if progress:
                    progress("history", len(coverage) + len(errors))
        return requested, period, frames, weekly, annual, errors, coverage

    @staticmethod
    def parameters():
        return {
            "initial_capital": ACCOUNT_CAPITAL,
            "deployment_limit": DEPLOYMENT_LIMIT,
            "cash_reserve": CASH_RESERVE,
            "max_positions": MAX_POSITIONS,
            "signal_interval": "1wk",
            "execution_interval": "1d",
            "timezone": "Asia/Kolkata",
            "ema": [50, 100],
            "rsi_wilder": 14,
            "macd": [12, 26, 9],
            "volume_average": "EMA30_including_completed_signal_week",
            "volume_multiplier": 1.0,
            "gap_down": "open_below_previous_week_close",
            "midpoint": "previous_open_close_body",
            "pivot_type": "Floor",
            "pivot_timeframe": "previous_calendar_year",
            "pivot_display_sets": 20,
            "entry_fill": "next_observed_daily_open_after_calendar_week_end_IST",
            "week_definition": (
                "Monday-Sunday; confirm Sunday 23:59:59 IST, "
                "including special weekend sessions"
            ),
            "stop": "one_tick_below_signal_week_low",
            "target": "entry_year_R2_frozen_for_position",
            "partial_exits": False,
            "R1": "reference_only",
            "same_bar_priority": "stop",
            "event_timestamps": (
                "session_open_IST_for_daily_intrabar_exits_sequence_unknown"
            ),
            "weekly_warmup": 100,
            "ema_seed": "first_observed_close_adjust_false",
            "first_observed_week_and_year": "discarded_as_potentially_partial",
            "annual_reference_coverage": (
                "weekday_year_boundaries_and_at_least_200_observed_sessions"
            ),
            "calendar_limitations": (
                "Provider session completeness is not independently "
                "exchange-calendar verified"
            ),
            "universe_limitations": (
                "Current constituents; point-in-time membership not established"
            ),
            "paper_execution_enabled": False,
            "broker_orders_allowed": False,
        }

    def scan(
        self,
        *,
        symbols,
        mode,
        period=None,
        top_n=1000,
        execute_paper=False,
        run_id=None,
        now=None,
        progress=None,
        tick_size=0.05,
        include_report_evidence=False,
        **_kwargs,
    ):
        if execute_paper:
            raise ValueError("Weekly Floor is scanner/backtest research only")
        top_n = int(self.technical._number("top_n", top_n, minimum=1, maximum=1000))
        self.technical._number("tick_size", tick_size, minimum=0.00001, maximum=100)
        requested = self.technical._symbols(symbols)
        if len(requested) > SCAN_BATCH_SIZE:
            rows, coverage, errors = [], [], []
            for offset in range(0, len(requested), SCAN_BATCH_SIZE):
                chunk = requested[offset : offset + SCAN_BATCH_SIZE]
                part = self.scan(
                    symbols=chunk,
                    mode=mode,
                    period=period,
                    top_n=len(chunk),
                    now=now,
                    tick_size=tick_size,
                    include_report_evidence=include_report_evidence,
                    progress=(
                        lambda phase, done, base=offset: progress(phase, base + done)
                    )
                    if progress
                    else None,
                )
                rows.extend(part["results"])
                coverage.extend(part["history_alignment"]["coverage"])
                errors.extend(part["history_alignment"]["excluded_symbols"])
            rows.sort(key=lambda row: (-row["score"], row["symbol"]))
            return {
                **part,
                "run_id": run_id or "weekly-scan-" + uuid4().hex,
                "requested_symbols": len(requested),
                "completed_symbols": len(requested) - len(errors),
                "error_symbols": len(errors),
                "entry_candidates": sum(r["signal"] == "BUY" for r in rows),
                "results": rows[:top_n],
                "parameters": {
                    **part["parameters"],
                    "history_fetch_batch_size": SCAN_BATCH_SIZE,
                },
                "history_alignment": {"coverage": coverage, "excluded_symbols": errors},
            }
        requested, period, frames, weeks, annual, errors, coverage = self._history(
            symbols, mode, period, now, progress, None
        )
        rows = []
        from services.institutional_stock_rating import load_snapshot, scanner_rating

        institutional = load_snapshot(self.technical)
        for symbol in frames:
            if local_now(now) - weeks[symbol].index[-1] > pd.Timedelta(days=10):
                errors.append(
                    {
                        "symbol": symbol,
                        "reason": "Completed weekly candle is stale",
                        "error_code": "WEEKLY_HISTORY_STALE",
                        **detail("CANDLES_STALE"),
                    }
                )
                continue
            signal = weekly_signal(
                weeks[symbol].iloc[-1],
                tick_size=tick_size,
                pivots=annual[symbol].get(local_now(now).year, {}),
            )
            rows.append(
                {
                    "symbol": symbol,
                    "side": "LONG",
                    "mode": mode,
                    "interval": "1wk",
                    "institutional_rating": scanner_rating(
                        institutional.get(symbol),
                        frames[symbol],
                        horizon="long_term",
                        now=local_now(now),
                    ),
                    **(
                        {
                            "_report_evidence": capture_report_evidence(
                                frames[symbol], horizon="long_term", now=local_now(now)
                            )
                        }
                        if include_report_evidence
                        else {}
                    ),
                    "bar_at": weeks[symbol].index[-1].isoformat(),
                    "close": number(weeks[symbol]["close"].iloc[-1]),
                    "signal": signal["signal"],
                    "score": signal["score"],
                    "confidence": signal["score"],
                    **signal["risk"],
                    "indicators": signal["indicators"],
                    "technical_evidence": signal["checks"],
                    "execution_eligible": False,
                    "execution_blocked_reason": "weekly_research_only_no_orders",
                    "signal_semantics": signal["signal_semantics"],
                    "fundamentals_used": False,
                    "data_status": "READY",
                    "observed_daily_bars": len(frames[symbol]),
                    "completed_weekly_bars": len(weeks[symbol]),
                }
            )
        rows.extend(
            {
                "symbol": e["symbol"],
                "signal": "ERROR",
                "score": 0.0,
                "error": e["reason"],
                "error_code": e.get("error_code", "WEEKLY_HISTORY_INCOMPLETE"),
                "execution_eligible": False,
                **{
                    key: e.get(key)
                    for key in (
                        "data_status",
                        "data_code",
                        "data_reason",
                        "retryable",
                        "observed_daily_bars",
                        "completed_weekly_bars",
                        "consecutive_completed_weeks",
                        "required_completed_weeks",
                    )
                },
            }
            for e in errors
        )
        rows.sort(key=lambda row: (-row["score"], row["symbol"]))
        from scanner.strategy_registry import REGISTRY_VERSION

        for row in rows:
            row["registry_version"] = REGISTRY_VERSION
            row["exit_policy_version"] = VERSION
        return {
            "status": "completed",
            "run_id": run_id or "weekly-scan-" + uuid4().hex,
            "exit_policy_version": VERSION,
            "registry_version": REGISTRY_VERSION,
            "strategy_id": STRATEGY_ID,
            "mode": mode,
            "interval": "1wk",
            "period": period,
            "results": rows[:top_n],
            "requested_symbols": len(requested),
            "completed_symbols": len(requested) - len(errors),
            "error_symbols": len(errors),
            "entry_candidates": sum(r["signal"] == "BUY" for r in rows),
            "parameters": {**self.parameters(), "tick_size_assumption": tick_size},
            "history_alignment": {"coverage": coverage, "excluded_symbols": errors},
            "engine": {"name": "WeeklyFloorResearch", "version": VERSION},
        }

    def backtest(
        self,
        *,
        symbols,
        mode,
        period=None,
        run_id=None,
        now=None,
        cost_bps=12.0,
        slippage_bps=5.0,
        progress=None,
        simulation_progress=None,
        report_horizon=None,
        report_stock_list=None,
        max_candle_rows=None,
        tick_size=0.05,
        comparison=False,
        **_kwargs,
    ):
        if comparison:
            from services.weekly_account_research import WeeklyAccountResearch

            return WeeklyAccountResearch(self).run(
                symbols=symbols,
                mode=mode,
                period=period,
                now=now,
                run_id=run_id,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                progress=progress,
                simulation_progress=simulation_progress,
                report_horizon=report_horizon,
                report_stock_list=report_stock_list,
                max_candle_rows=max_candle_rows,
                tick_size=tick_size,
            )
        from scanner.strategy_registry import get_strategy
        from services.research_report import build_report

        self.technical._number("tick_size", tick_size, minimum=0.00001, maximum=100)
        self.technical._number("cost_bps", cost_bps, minimum=0, maximum=1000)
        self.technical._number("slippage_bps", slippage_bps, minimum=0, maximum=1000)
        run_id = run_id or "weekly-backtest-" + uuid4().hex
        if self.technical.repository.by_run_id(run_id) is not None:
            raise ValueError("backtest run_id already exists")
        requested, period, frames, weekly, annual, errors, coverage = self._history(
            symbols, mode, period, now, progress, max_candle_rows
        )
        if not frames:
            raise ValueError(
                "No stocks have 100 complete weekly bars and prior-year Floor pivots"
            )
        frames, alignment = align_history(frames)
        result = {
            "status": "completed",
            "run_id": run_id,
            "strategy_id": STRATEGY_ID,
            "strategy": get_strategy(STRATEGY_ID),
            "mode": mode,
            "period": period,
            "interval": "1wk",
            "requested_symbols": requested,
            "symbols": sorted(frames),
            **simulate_weekly(
                frames,
                weekly,
                annual,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                tick_size=tick_size,
                progress=simulation_progress,
            ),
            "parameters": {
                **self.parameters(),
                "cost_bps": cost_bps,
                "slippage_bps": slippage_bps,
                "tick_size_assumption": tick_size,
            },
            "history_alignment": {
                **alignment,
                "coverage": coverage,
                "history_errors": errors,
            },
            "created_at": self.technical._timestamp(),
            "safety": {
                "historical_simulation_only": True,
                "paper_orders_created": False,
                "broker_orders_allowed": False,
            },
        }
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
                    key: metrics[key]
                    for key in (
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
                "cost_bps": cost_bps,
                "slippage_bps": slippage_bps,
                "parameters": result["parameters"],
                "result": result,
                "created_at": result["created_at"],
            }
        )
        return result
