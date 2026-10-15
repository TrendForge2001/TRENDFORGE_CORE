"""Canonical paper-trading service with fail-closed production controls."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from services.paper_trading_runtime import PaperTradingRuntime


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class PaperTradingDisabledError(RuntimeError):
    pass


class PaperTradingKillSwitchError(RuntimeError):
    pass


class PaperTradingService:
    """Paper-only execution boundary.

    The service never calls a broker order endpoint. Opening new simulated
    positions requires explicit environment activation and an open kill switch.
    Monitoring/closing remains available even when new entries are disabled.
    """

    def __init__(
        self,
        runtime: PaperTradingRuntime | None = None,
        *,
        enabled: bool | None = None,
        environment_kill_switch: bool | None = None,
    ) -> None:
        self.runtime = runtime or PaperTradingRuntime()
        self.enabled = (
            _enabled("TRENDFORGE_PAPER_TRADING_ENABLED", False)
            if enabled is None
            else bool(enabled)
        )
        self.environment_kill_switch = (
            _enabled(
                "TRENDFORGE_PAPER_TRADING_KILL_SWITCH",
                True,
            )
            if environment_kill_switch is None
            else bool(environment_kill_switch)
        )
        self.runtime_kill_switch = False
        self.restored_open_trades = 0

    @property
    def kill_switch(self) -> bool:
        return bool(
            self.environment_kill_switch
            or self.runtime_kill_switch
        )

    @property
    def can_open_new_positions(self) -> bool:
        return bool(self.enabled and not self.kill_switch)

    def restore_open(self) -> int:
        self.restored_open_trades = int(
            self.runtime.restore_open()
        )
        return self.restored_open_trades

    def open(
        self,
        order: Any,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise PaperTradingDisabledError(
                "Paper trading is disabled by production configuration"
            )
        if self.kill_switch:
            raise PaperTradingKillSwitchError(
                "Paper trading kill switch is active"
            )

        trade_id = self.runtime.open(order, now=now)
        return {
            "status": "opened",
            "trade_id": trade_id,
            **self.snapshot(),
        }

    def monitor(
        self,
        quotes: dict[str, float],
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        normalized = {
            str(symbol).strip().upper(): float(price)
            for symbol, price in (quotes or {}).items()
            if str(symbol).strip()
        }
        closed = self.runtime.monitor(
            normalized,
            now=now,
        )
        return {
            "status": "monitored",
            "closed": closed,
            **self.snapshot(),
        }

    def set_runtime_kill_switch(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        self.runtime_kill_switch = bool(enabled)
        return self.health()

    def snapshot(self) -> dict[str, Any]:
        payload = dict(self.runtime.snapshot())
        payload.update(
            {
                "mode": "paper_only",
                "broker_orders_allowed": False,
                "enabled": self.enabled,
                "kill_switch": self.kill_switch,
                "environment_kill_switch": (
                    self.environment_kill_switch
                ),
                "runtime_kill_switch": (
                    self.runtime_kill_switch
                ),
                "can_open_new_positions": (
                    self.can_open_new_positions
                ),
            }
        )
        return payload

    def health(self) -> dict[str, Any]:
        portfolio = getattr(self.runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        open_positions = (
            len(positions)
            if isinstance(positions, dict)
            else 0
        )
        return {
            "status": (
                "ready"
                if self.can_open_new_positions
                else "locked"
                if self.enabled
                else "disabled"
            ),
            "mode": "paper_only",
            "broker_orders_allowed": False,
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "environment_kill_switch": (
                self.environment_kill_switch
            ),
            "runtime_kill_switch": self.runtime_kill_switch,
            "can_open_new_positions": (
                self.can_open_new_positions
            ),
            "open_positions": open_positions,
            "restored_open_trades": (
                self.restored_open_trades
            ),
            "market_open_time_ist": "09:15",
            "entry_cutoff_time_ist": "15:00",
            "force_exit_time_ist": "15:00",
        }

    def close(self) -> None:
        self.runtime.close()


__all__ = [
    "PaperTradingDisabledError",
    "PaperTradingKillSwitchError",
    "PaperTradingService",
]
