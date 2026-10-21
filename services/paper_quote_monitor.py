"""Live Kite quote monitor for canonical paper trading."""
from __future__ import annotations

import asyncio
from datetime import datetime
import os
from typing import Any

from zoneinfo import ZoneInfo


class PaperQuoteMonitor:
    """Poll live quotes for open paper positions and apply exits.

    The monitor is paper-only. It reads LTPs from the configured quote provider
    and delegates all simulated exit decisions to PaperTradingService.
    """

    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(
        self,
        paper_service: Any,
        quote_provider: Any,
        *,
        enabled: bool | None = None,
        poll_interval_seconds: float | None = None,
        idle_interval_seconds: float | None = None,
        notifications: Any | None = None,
        strategy_monitor: Any | None = None,
    ) -> None:
        self.paper_service = paper_service
        self.quote_provider = quote_provider
        self.notifications = notifications
        self.strategy_monitor = strategy_monitor
        self.enabled = (
            self._env_enabled(
                "TRENDFORGE_PAPER_MONITOR_ENABLED",
                False,
            )
            if enabled is None
            else bool(enabled)
        )
        self.poll_interval_seconds = (
            self._env_float(
                "TRENDFORGE_PAPER_MONITOR_INTERVAL_SECONDS",
                15.0,
                minimum=5.0,
                maximum=300.0,
            )
            if poll_interval_seconds is None
            else max(5.0, float(poll_interval_seconds))
        )
        self.idle_interval_seconds = (
            self._env_float(
                "TRENDFORGE_PAPER_MONITOR_IDLE_SECONDS",
                30.0,
                minimum=5.0,
                maximum=600.0,
            )
            if idle_interval_seconds is None
            else max(5.0, float(idle_interval_seconds))
        )

        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._running = False

        self.iterations = 0
        self.quote_success_count = 0
        self.quote_failure_count = 0
        self.closed_count = 0
        self.last_poll_at: str | None = None
        self.last_success_at: str | None = None
        self.last_error_at: str | None = None
        self.last_error: str | None = None
        self.last_symbols: list[str] = []
        self.last_quotes: dict[str, float] = {}
        self.last_closed: list[dict[str, Any]] = []
        self.last_strategy_monitor: dict[str, Any] | None = None
        self.last_strategy_monitor_error: str | None = None

    @staticmethod
    def _env_enabled(name: str, default: bool) -> bool:
        value = os.getenv(name)
        if value is None:
            return default
        return str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
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

    def _open_symbols(self) -> list[str]:
        runtime = getattr(self.paper_service, "runtime", None)
        portfolio = getattr(runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        if not isinstance(positions, dict):
            return []
        return sorted(
            {
                str(symbol).strip().upper()
                for symbol in positions
                if str(symbol).strip()
            }
        )

    @staticmethod
    def _parse_ltp(
        raw: Any,
        symbols: list[str],
    ) -> dict[str, float]:
        if not isinstance(raw, dict):
            raise ValueError("Quote provider returned invalid LTP payload")

        quotes: dict[str, float] = {}
        for symbol in symbols:
            candidates = (
                f"NSE:{symbol}",
                symbol,
            )
            row = None
            for key in candidates:
                if key in raw:
                    row = raw[key]
                    break

            if isinstance(row, dict):
                price = row.get("last_price")
            else:
                price = row

            if price is None:
                continue

            try:
                value = float(price)
            except (TypeError, ValueError):
                continue

            if value > 0:
                quotes[symbol] = value

        return quotes

    def _fetch_quotes(
        self,
        symbols: list[str],
    ) -> dict[str, float]:
        instruments = [f"NSE:{symbol}" for symbol in symbols]

        validate = getattr(
            self.quote_provider,
            "validate_live_session",
            None,
        )
        if callable(validate):
            validate()

        fetcher = getattr(
            self.quote_provider,
            "safe_ltp",
            None,
        )
        if not callable(fetcher):
            fetcher = getattr(
                self.quote_provider,
                "ltp",
                None,
            )
        if not callable(fetcher):
            raise RuntimeError(
                "Configured quote provider does not expose ltp()"
            )

        raw = fetcher(instruments)
        quotes = self._parse_ltp(raw, symbols)
        if len(quotes) != len(symbols):
            missing = [
                symbol for symbol in symbols
                if symbol not in quotes
            ]
            raise RuntimeError(
                "Live quote missing for paper position(s): "
                + ", ".join(missing)
            )
        return quotes

    def tick(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(self.MARKET_TZ)
        self.iterations += 1
        self.last_poll_at = current.isoformat()

        symbols = self._open_symbols()
        self.last_symbols = symbols

        if not symbols:
            self.last_quotes = {}
            self.last_closed = []
            self.last_error = None
            return {
                "status": "idle",
                "symbols": [],
                "quotes": {},
                "closed": [],
            }

        try:
            quotes = self._fetch_quotes(symbols)
            result = self.paper_service.monitor(
                quotes,
                now=current,
            )
        except Exception as exc:
            self.quote_failure_count += 1
            self.last_error_at = current.isoformat()
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._notify_failure(self.last_error)
            raise

        closed = list(result.get("closed") or [])

        strategy_result = None
        strategy_monitor = self.strategy_monitor
        if strategy_monitor is not None:
            method = getattr(strategy_monitor, "maybe_tick", None)
            if callable(method):
                try:
                    strategy_result = method(now=current)
                    self.last_strategy_monitor = (
                        dict(strategy_result)
                        if isinstance(strategy_result, dict)
                        else {"status": "invalid_result"}
                    )
                    self.last_strategy_monitor_error = None
                except Exception as exc:
                    self.last_strategy_monitor_error = (
                        f"{type(exc).__name__}: {exc}"
                    )

        self.quote_success_count += 1
        self.closed_count += len(closed)
        self.last_success_at = current.isoformat()
        self.last_error = None
        self.last_quotes = dict(quotes)
        self.last_closed = closed

        return {
            "status": "monitored",
            "symbols": symbols,
            "quotes": quotes,
            "closed": closed,
            "open_positions": result.get("open_positions"),
            "total_pnl": result.get("total_pnl"),
            "strategy_exit_monitor": strategy_result,
            "strategy_exit_monitor_error": (
                self.last_strategy_monitor_error
            ),
        }

    def _notify_failure(
        self,
        error: str,
    ) -> None:
        method = getattr(
            self.notifications,
            "monitor_failed",
            None,
        )
        if not callable(method):
            return
        try:
            method(error=error)
        except Exception:
            pass

    async def _run(self) -> None:
        self._running = True
        try:
            while self._stop_event is not None:
                if self._stop_event.is_set():
                    break

                delay = self.idle_interval_seconds
                if self.enabled:
                    try:
                        result = await asyncio.to_thread(self.tick)
                        if result.get("status") == "monitored":
                            delay = self.poll_interval_seconds
                    except Exception:
                        delay = self.poll_interval_seconds

                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=delay,
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            self._running = False

    async def start(self) -> bool:
        if not self.enabled:
            return False
        if self._task is not None and not self._task.done():
            return True

        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(
            self._run(),
            name="trendforge-paper-quote-monitor",
        )
        return True

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await self._task
            finally:
                self._task = None
        self._stop_event = None
        self._running = False

    def health(self) -> dict[str, Any]:
        symbols = self._open_symbols()
        return {
            "status": (
                "running"
                if self.enabled and self._running
                else "starting"
                if self.enabled
                else "disabled"
            ),
            "enabled": self.enabled,
            "running": self._running,
            "quote_source": type(
                self.quote_provider
            ).__name__,
            "poll_interval_seconds": self.poll_interval_seconds,
            "idle_interval_seconds": self.idle_interval_seconds,
            "open_position_count": len(symbols),
            "open_symbols": symbols,
            "iterations": self.iterations,
            "quote_success_count": self.quote_success_count,
            "quote_failure_count": self.quote_failure_count,
            "closed_count": self.closed_count,
            "last_poll_at": self.last_poll_at,
            "last_success_at": self.last_success_at,
            "last_error_at": self.last_error_at,
            "last_error": self.last_error,
            "last_symbols": list(self.last_symbols),
            "last_quotes": dict(self.last_quotes),
            "last_closed": list(self.last_closed),
            "strategy_exit_monitor": (
                self.strategy_monitor.health()
                if self.strategy_monitor is not None
                and callable(
                    getattr(self.strategy_monitor, "health", None)
                )
                else {"status": "not_configured"}
            ),
            "last_strategy_monitor": self.last_strategy_monitor,
            "last_strategy_monitor_error": (
                self.last_strategy_monitor_error
            ),
            "broker_orders_allowed": False,
        }


__all__ = ["PaperQuoteMonitor"]
