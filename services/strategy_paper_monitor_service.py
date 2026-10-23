"""R72.5.5 strategy-aware paper position monitoring and attribution."""
from __future__ import annotations

from datetime import datetime
import os
from typing import Any
from zoneinfo import ZoneInfo


class StrategyPaperMonitorService:
    """Evaluate each open strategy paper position against its own exit rule.

    The service is paper-only. It reads completed Kite candles, evaluates only
    the strategy that opened the position, and delegates simulated closes to
    PaperTradingService. It never places broker orders.
    """

    VERSION = "R72.5.5-v1"
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    SUPPORTED_MODES = frozenset({"intraday", "swing"})

    def __init__(
        self,
        *,
        scanner_service: Any,
        paper_service: Any,
        quote_provider: Any,
        enabled: bool | None = None,
        check_interval_seconds: float | None = None,
    ) -> None:
        if scanner_service is None:
            raise TypeError("scanner_service is required")
        if paper_service is None:
            raise TypeError("paper_service is required")
        self.scanner = scanner_service
        self.paper_service = paper_service
        self.quote_provider = quote_provider
        self.enabled = (
            self._env_enabled(
                "TRENDFORGE_STRATEGY_PAPER_MONITOR_ENABLED",
                False,
            )
            if enabled is None
            else bool(enabled)
        )
        self.check_interval_seconds = (
            self._env_float(
                "TRENDFORGE_STRATEGY_PAPER_MONITOR_INTERVAL_SECONDS",
                300.0,
                minimum=60.0,
                maximum=3600.0,
            )
            if check_interval_seconds is None
            else max(60.0, float(check_interval_seconds))
        )
        self.iterations = 0
        self.exit_signal_count = 0
        self.closed_count = 0
        self.error_count = 0
        self.last_checked_at: str | None = None
        self.last_success_at: str | None = None
        self.last_error: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._last_checked_dt: datetime | None = None

    @staticmethod
    def _env_enabled(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {
            "1", "true", "yes", "on",
        }

    @staticmethod
    def _env_float(
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float,
    ) -> float:
        raw = os.getenv(name)
        try:
            value = float(raw) if raw is not None else float(default)
        except (TypeError, ValueError):
            value = float(default)
        return min(max(value, minimum), maximum)

    @staticmethod
    def _clean(value: Any) -> str:
        return str(value or "").strip()

    @staticmethod
    def _positions(paper_service: Any) -> dict[str, Any]:
        runtime = getattr(paper_service, "runtime", None)
        portfolio = getattr(runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        return positions if isinstance(positions, dict) else {}

    def strategy_positions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for symbol, position in self._positions(self.paper_service).items():
            strategy_id = self._clean(
                getattr(position, "strategy_id", None)
            ).lower()
            if not strategy_id:
                continue
            rows.append(
                {
                    "symbol": str(symbol).upper(),
                    "strategy_id": strategy_id,
                    "strategy_name": getattr(
                        position, "strategy_name", None
                    ),
                    "strategy_source": getattr(
                        position, "strategy_source", None
                    ),
                    "trade_mode": self._clean(
                        getattr(position, "trade_mode", None)
                    ).lower(),
                    "source_scan_run_id": getattr(
                        position, "source_scan_run_id", None
                    ),
                    "validation_run_id": getattr(
                        position, "validation_run_id", None
                    ),
                    "strategy_score": float(
                        getattr(position, "strategy_score", 0.0) or 0.0
                    ),
                    "consensus_score": float(
                        getattr(position, "consensus_score", 0.0) or 0.0
                    ),
                    "entry_signal": getattr(
                        position, "entry_signal", None
                    ),
                    "entry_bar_at": getattr(
                        position, "entry_bar_at", None
                    ),
                    "entry_price": float(
                        getattr(position, "average_price", 0.0) or 0.0
                    ),
                    "ltp": float(
                        getattr(position, "ltp", 0.0) or 0.0
                    ),
                    "quantity": int(
                        getattr(position, "quantity", 0) or 0
                    ),
                    "unrealized_pnl": float(
                        getattr(position, "pnl", 0.0) or 0.0
                    ),
                    "unrealized_pnl_pct": float(
                        getattr(position, "pnl_percent", 0.0) or 0.0
                    ),
                }
            )
        return sorted(
            rows,
            key=lambda row: (
                row["trade_mode"],
                row["strategy_id"],
                row["symbol"],
            ),
        )

    @staticmethod
    def _evaluation(
        payload: dict[str, Any],
        strategy_id: str,
    ) -> dict[str, Any] | None:
        for row in payload.get("evaluations") or []:
            if (
                isinstance(row, dict)
                and str(row.get("strategy_id") or "").strip().lower()
                == strategy_id
            ):
                return row
        return None

    def _quote(self, symbol: str) -> float:
        if self.quote_provider is None:
            raise RuntimeError("Kite quote provider is unavailable")
        validate = getattr(
            self.quote_provider,
            "validate_live_session",
            None,
        )
        if callable(validate):
            validate()
        fetcher = getattr(self.quote_provider, "safe_ltp", None)
        if not callable(fetcher):
            fetcher = getattr(self.quote_provider, "ltp", None)
        if not callable(fetcher):
            raise RuntimeError("Quote provider does not expose ltp()")
        key = f"NSE:{symbol}"
        raw = fetcher([key])
        if not isinstance(raw, dict):
            raise RuntimeError("Quote provider returned invalid payload")
        row = raw.get(key)
        value = (
            row.get("last_price")
            if isinstance(row, dict)
            else row
        )
        price = float(value or 0.0)
        if price <= 0:
            raise RuntimeError(f"Live quote unavailable for {symbol}")
        return price

    def _evaluate_mode(
        self,
        positions: list[dict[str, Any]],
        *,
        mode: str,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        _, interval, period = self.scanner._mode_config(mode, None)
        symbols = [row["symbol"] for row in positions]
        frames, failures = self.scanner.market_data.batch_candles_with_errors(
            symbols,
            period=period,
            interval=interval,
        )
        evaluations: list[dict[str, Any]] = []
        exit_candidates: list[dict[str, Any]] = []

        for position in positions:
            symbol = position["symbol"]
            strategy_id = position["strategy_id"]
            raw = frames.get(symbol)
            if raw is None:
                evaluations.append(
                    {
                        **position,
                        "status": "error",
                        "error": failures.get(
                            symbol,
                            "Kite returned no candle data",
                        ),
                    }
                )
                continue
            try:
                completed = self.scanner._completed_bars(
                    raw,
                    interval=interval,
                    now=now,
                )
                if getattr(self, "require_fresh_candles", False):
                    from services.technical_trading_service import TechnicalTradingService
                    reason = TechnicalTradingService._execution_block_reason(
                        completed, mode=mode, now=now,
                    )
                    if mode == "intraday":
                        # Exits remain available after the entry cutoff.
                        stamp = TechnicalTradingService._as_ist(completed.index[-1])
                        from datetime import timedelta
                        if (stamp is None or stamp.date() != now.date()
                            or not 0 <= (now - stamp - timedelta(minutes=15)).total_seconds() < 900):
                            raise ValueError("Current completed Kite candles are required")
                    elif reason:
                        raise ValueError("Current completed Kite candles are required")
                if len(completed) < 120:
                    raise ValueError(
                        "At least 120 completed candles are required"
                    )
                frame = self.scanner.indicators.calculate(
                    completed.copy()
                )
                if mode == "intraday":
                    frame = self.scanner._intraday_session_overrides(
                        frame
                    )
                result = self.scanner.strategies.evaluate(
                    frame,
                    mode=mode,
                    interval=interval,
                    source="all",
                    strategy_ids=[strategy_id],
                )
                evaluation = self._evaluation(
                    result,
                    strategy_id,
                )
                if evaluation is None:
                    raise RuntimeError(
                        "Strategy evaluation was not returned"
                    )
                signal = self._clean(
                    evaluation.get("signal")
                ).upper()
                row = {
                    **position,
                    "status": "evaluated",
                    "bar_at": self.scanner._label(frame.index[-1]),
                    "exit_signal": signal,
                    "exit_strategy_score": float(
                        evaluation.get("score") or 0.0
                    ),
                    "passed_checks": list(
                        evaluation.get("passed_checks") or []
                    ),
                    "failed_checks": list(
                        evaluation.get("failed_checks") or []
                    ),
                    "exit_triggered": signal == "EXIT",
                }
                evaluations.append(row)
                if signal == "EXIT":
                    exit_candidates.append(row)
            except Exception as exc:
                evaluations.append(
                    {
                        **position,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return evaluations, exit_candidates

    def tick(
        self,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        current = now or datetime.now(self.MARKET_TZ)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.MARKET_TZ)
        else:
            current = current.astimezone(self.MARKET_TZ)

        if not self.enabled and not force:
            return {
                "status": "disabled",
                "version": self.VERSION,
                "broker_orders_allowed": False,
                "closed": [],
                "evaluations": [],
            }

        self.iterations += 1
        self.last_checked_at = current.isoformat()
        self._last_checked_dt = current
        positions = self.strategy_positions()
        if not positions:
            result = {
                "status": "idle",
                "version": self.VERSION,
                "checked_at": current.isoformat(),
                "strategy_positions": 0,
                "evaluations": [],
                "exit_signals": [],
                "closed": [],
                "broker_orders_allowed": False,
            }
            self.last_result = result
            self.last_success_at = current.isoformat()
            self.last_error = None
            return result

        evaluations: list[dict[str, Any]] = []
        exit_candidates: list[dict[str, Any]] = []
        for mode in sorted(self.SUPPORTED_MODES):
            selected = [
                row for row in positions
                if row["trade_mode"] == mode
            ]
            if not selected:
                continue
            mode_evaluations, mode_exits = self._evaluate_mode(
                selected,
                mode=mode,
                now=current,
            )
            evaluations.extend(mode_evaluations)
            exit_candidates.extend(mode_exits)

        unsupported = [
            row for row in positions
            if row["trade_mode"] not in self.SUPPORTED_MODES
        ]
        for row in unsupported:
            evaluations.append(
                {
                    **row,
                    "status": "blocked",
                    "error": "paper_mode_not_supported",
                }
            )

        closed: list[dict[str, Any]] = []
        close_errors: list[dict[str, Any]] = []
        for candidate in exit_candidates:
            symbol = candidate["symbol"]
            try:
                price = self._quote(symbol)
                response = self.paper_service.close_strategy_exit(
                    symbol,
                    price,
                    exit_signal=candidate["exit_signal"],
                    exit_signal_at=candidate["bar_at"],
                    exit_strategy_score=candidate[
                        "exit_strategy_score"
                    ],
                    now=current,
                )
                row = response.get("closed")
                if isinstance(row, dict):
                    closed.append(row)
            except Exception as exc:
                close_errors.append(
                    {
                        "symbol": symbol,
                        "strategy_id": candidate["strategy_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        self.exit_signal_count += len(exit_candidates)
        self.closed_count += len(closed)
        self.error_count += sum(
            1 for row in evaluations
            if row.get("status") == "error"
        ) + len(close_errors)
        self.last_success_at = current.isoformat()
        self.last_error = (
            close_errors[0]["error"]
            if close_errors
            else None
        )
        result = {
            "status": (
                "closed"
                if closed
                else "degraded"
                if close_errors
                else "monitored"
            ),
            "version": self.VERSION,
            "checked_at": current.isoformat(),
            "strategy_positions": len(positions),
            "evaluations": evaluations,
            "exit_signals": exit_candidates,
            "closed": closed,
            "close_errors": close_errors,
            "broker_orders_allowed": False,
            "paper_only": True,
        }
        self.last_result = result
        return result

    def maybe_tick(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(self.MARKET_TZ)
        if not self.enabled:
            return {
                "status": "disabled",
                "version": self.VERSION,
                "closed": [],
            }
        if self._last_checked_dt is not None:
            probe = current
            if probe.tzinfo is None:
                probe = probe.replace(tzinfo=self.MARKET_TZ)
            else:
                probe = probe.astimezone(self.MARKET_TZ)
            elapsed = (
                probe - self._last_checked_dt
            ).total_seconds()
            if elapsed < self.check_interval_seconds:
                return {
                    "status": "throttled",
                    "version": self.VERSION,
                    "next_check_in_seconds": round(
                        self.check_interval_seconds - elapsed,
                        2,
                    ),
                    "closed": [],
                }
        return self.tick(now=current)

    def performance(self) -> dict[str, Any]:
        runtime = getattr(self.paper_service, "runtime", None)
        repository = getattr(runtime, "trades", None)
        method = getattr(repository, "strategy_performance", None)
        rows = method() if callable(method) else []
        return {
            "status": "ready",
            "version": self.VERSION,
            "strategy_count": len(rows or []),
            "rows": list(rows or []),
            "open_strategy_positions": self.strategy_positions(),
            "paper_only": True,
            "broker_orders_allowed": False,
        }

    def trades(
        self,
        strategy_id: str | None = None,
        *,
        limit: int = 200,
    ) -> dict[str, Any]:
        runtime = getattr(self.paper_service, "runtime", None)
        repository = getattr(runtime, "trades", None)
        method = getattr(repository, "strategy_trades", None)
        rows = (
            method(strategy_id, limit=limit)
            if callable(method)
            else []
        )
        return {
            "status": "ready",
            "version": self.VERSION,
            "strategy_id": (
                self._clean(strategy_id).lower() or None
            ),
            "count": len(rows or []),
            "rows": list(rows or []),
            "paper_only": True,
            "broker_orders_allowed": False,
        }

    def health(self) -> dict[str, Any]:
        positions = self.strategy_positions()
        return {
            "status": "ready" if self.enabled else "disabled",
            "version": self.VERSION,
            "enabled": self.enabled,
            "check_interval_seconds": self.check_interval_seconds,
            "strategy_position_count": len(positions),
            "strategy_positions": positions,
            "iterations": self.iterations,
            "exit_signal_count": self.exit_signal_count,
            "closed_count": self.closed_count,
            "error_count": self.error_count,
            "last_checked_at": self.last_checked_at,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
            "last_result": self.last_result,
            "paper_only": True,
            "broker_orders_allowed": False,
            "completed_candles_only": True,
            "automatic_close_requires_enabled": True,
            "manual_admin_tick_available": True,
        }


__all__ = ["StrategyPaperMonitorService"]
