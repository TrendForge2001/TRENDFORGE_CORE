"""Canonical paper-trading service with fail-closed production controls."""

from __future__ import annotations

import os
import logging
import threading
from datetime import datetime
from typing import Any
from uuid import uuid4

from core.paper_storage_policy import paper_entry_storage_policy
from services.paper_trading_runtime import PaperTradingRuntime

_LOG = logging.getLogger("trendforge.paper.controls")


def _enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class PaperTradingDisabledError(RuntimeError):
    pass


class PaperTradingKillSwitchError(RuntimeError):
    pass


class PaperTradingStorageError(PaperTradingDisabledError):
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
        notifications: Any | None = None,
    ) -> None:
        self.runtime = runtime or PaperTradingRuntime()
        self.notifications = notifications
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
        self._entry_lock = threading.RLock()
        self._kill_switch_storage: dict[str, Any] = {"status": "process_memory_only"}
        self.restored_open_trades = 0
        loader = getattr(self.runtime, "load_kill_switch", None)
        if callable(loader):
            try:
                restored = loader()
                if restored is not None:
                    self.runtime_kill_switch = bool(restored)
                    self._kill_switch_storage = {"status": "persisted"}
            except Exception:
                self._kill_persistence_failed()

    @property
    def kill_switch(self) -> bool:
        return bool(self.environment_kill_switch or self.runtime_kill_switch)

    @property
    def can_open_new_positions(self) -> bool:
        return bool(
            self.enabled
            and not self.kill_switch
            and self.entry_storage_policy()["entry_allowed"]
        )

    def entry_storage_policy(self) -> dict[str, Any]:
        repository = getattr(self.runtime, "trades", None)
        database = getattr(repository, "db", None)
        actual_path = getattr(database, "db_path", None)
        policy = paper_entry_storage_policy(runtime_database_path=actual_path)
        if (
            policy["mode"] == "durable"
            and self._kill_switch_storage["status"] != "persisted"
        ):
            return {
                **policy,
                "entry_allowed": False,
                "mode": "blocked",
                "reason": "kill_control_storage_unavailable",
                "message": "Saved paper kill-switch state is unavailable; new entries are blocked.",
            }
        return policy

    def _kill_persistence_failed(self) -> None:
        # Fail closed in memory even when the database cannot record the kill.
        self.runtime_kill_switch = True
        reference = uuid4().hex[:12]
        self._kill_switch_storage = {"status": "unavailable", "reference": reference}
        _LOG.warning("paper_kill_persistence_unavailable reference=%s", reference)

    def restore_open(self) -> int:
        self.restored_open_trades = int(self.runtime.restore_open())
        return self.restored_open_trades

    def open(
        self,
        order: Any,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        with self._entry_lock:
            return self._open(order, now=now)

    def _open(self, order: Any, *, now: datetime | None = None) -> dict[str, Any]:
        if not self.enabled:
            message = "Paper trading is disabled by production configuration"
            self._notify_paper_blocked(order, message)
            raise PaperTradingDisabledError(message)
        if self.kill_switch:
            message = "Paper trading kill switch is active"
            self._notify_paper_blocked(order, message)
            raise PaperTradingKillSwitchError(message)

        policy = self.entry_storage_policy()
        if not policy["entry_allowed"]:
            message = policy["message"]
            self._notify_paper_blocked(order, message)
            raise PaperTradingStorageError(message)

        trade_id = self.runtime.open(order, now=now)
        self._notify_paper_opened(order, trade_id)
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
        for row in closed:
            self._notify_paper_closed(row)
        return {
            "status": "monitored",
            "closed": closed,
            **self.snapshot(),
        }

    def close_strategy_exit(
        self,
        symbol: str,
        exit_price: float,
        *,
        exit_signal: str,
        exit_signal_at: str | None = None,
        exit_strategy_score: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Close an existing simulated position on its own strategy exit.

        Closing is always allowed even when new paper entries are disabled or
        the kill switch is active. This method never calls a broker endpoint.
        """
        row = self.runtime.close_strategy_exit(
            symbol,
            exit_price,
            exit_signal=exit_signal,
            exit_signal_at=exit_signal_at,
            exit_strategy_score=exit_strategy_score,
            now=now,
        )
        self._notify_paper_closed(row)
        return {
            "status": "closed",
            "closed": row,
            **self.snapshot(),
        }

    def set_runtime_kill_switch(
        self,
        enabled: bool,
    ) -> dict[str, Any]:
        with self._entry_lock:
            previous = self.runtime_kill_switch
            if enabled:
                self.runtime_kill_switch = True
            saver = getattr(self.runtime, "save_kill_switch", None)
            try:
                persisted = saver(bool(enabled)) if callable(saver) else False
            except Exception:
                self._kill_persistence_failed()
            else:
                self.runtime_kill_switch = bool(enabled)
                self._kill_switch_storage = {
                    "status": "persisted" if persisted else "process_memory_only"
                }
            changed = previous != self.runtime_kill_switch
        if changed:
            self._notify_kill_switch(self.runtime_kill_switch)
        return self.health()

    def _notify_paper_blocked(
        self,
        order: Any,
        reason: str,
    ) -> None:
        method = getattr(
            self.notifications,
            "paper_open_blocked",
            None,
        )
        if not callable(method):
            return
        try:
            method(
                symbol=getattr(order, "symbol", None),
                reason=reason,
            )
        except Exception:
            pass

    def _notify_paper_opened(
        self,
        order: Any,
        trade_id: Any,
    ) -> None:
        method = getattr(
            self.notifications,
            "paper_opened",
            None,
        )
        if not callable(method):
            return
        try:
            method(
                trade_id=trade_id,
                symbol=getattr(order, "symbol", ""),
                side=getattr(order, "side", "BUY"),
                quantity=getattr(order, "quantity", 0),
                entry_price=getattr(order, "price", 0.0),
                stoploss=getattr(order, "stoploss", None),
                target=getattr(order, "target2", None),
                source="paper_trading",
            )
        except Exception:
            # Notification routing is observational and must never
            # change the paper-trading outcome.
            pass

    def _notify_paper_closed(
        self,
        row: dict[str, Any],
    ) -> None:
        method = getattr(
            self.notifications,
            "paper_closed",
            None,
        )
        if not callable(method):
            return
        try:
            method(
                row,
                source="paper_trading",
            )
        except Exception:
            pass

    def _notify_kill_switch(
        self,
        enabled: bool,
    ) -> None:
        method = getattr(
            self.notifications,
            "kill_switch_changed",
            None,
        )
        if not callable(method):
            return
        try:
            method(enabled=enabled)
        except Exception:
            pass

    def snapshot(self) -> dict[str, Any]:
        payload = dict(self.runtime.snapshot())
        policy = self.entry_storage_policy()
        payload.update(
            {
                "mode": "paper_only",
                "broker_orders_allowed": False,
                "enabled": self.enabled,
                "kill_switch": self.kill_switch,
                "environment_kill_switch": (self.environment_kill_switch),
                "runtime_kill_switch": (self.runtime_kill_switch),
                "can_open_new_positions": (
                    bool(
                        self.enabled
                        and not self.kill_switch
                        and policy["entry_allowed"]
                    )
                ),
                "entry_storage_policy": policy,
                "kill_switch_storage": dict(self._kill_switch_storage),
            }
        )
        return payload

    def health(self) -> dict[str, Any]:
        policy = self.entry_storage_policy()
        can_open = bool(
            self.enabled and not self.kill_switch and policy["entry_allowed"]
        )
        portfolio = getattr(self.runtime, "portfolio", None)
        positions = getattr(portfolio, "positions", {})
        open_positions = len(positions) if isinstance(positions, dict) else 0
        return {
            "status": (
                "ready" if can_open else "locked" if self.enabled else "disabled"
            ),
            "mode": "paper_only",
            "broker_orders_allowed": False,
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "environment_kill_switch": (self.environment_kill_switch),
            "runtime_kill_switch": self.runtime_kill_switch,
            "can_open_new_positions": (can_open),
            "entry_storage_policy": policy,
            "kill_switch_storage": dict(self._kill_switch_storage),
            "open_positions": open_positions,
            "restored_open_trades": (self.restored_open_trades),
            "market_open_time_ist": "09:15",
            "entry_cutoff_time_ist": "15:00",
            "force_exit_time_ist": "15:00",
            "intraday_force_exit_time_ist": "15:00",
            "swing_force_exit_time_ist": None,
        }

    def close(self) -> None:
        self.runtime.close()


__all__ = [
    "PaperTradingDisabledError",
    "PaperTradingKillSwitchError",
    "PaperTradingStorageError",
    "PaperTradingService",
]
