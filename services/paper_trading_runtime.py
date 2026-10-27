"""Persistent paper-trading runtime with SL, targets and strategy exits."""

from __future__ import annotations

import threading
from datetime import datetime, time
from math import fsum, isfinite
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from database.repositories.trade_repository import TradeRepository
from execution.portfolio_manager import PortfolioManager


class PaperTradingRuntime:
    FORCE_EXIT_TIME = time(15, 0)
    MARKET_OPEN_TIME = time(9, 15)
    MARKET_TZ = ZoneInfo("Asia/Kolkata")
    KILL_SWITCH_SETTING = "paper_trading.runtime_kill_switch"

    def __init__(self, portfolio=None, trades=None) -> None:
        self.portfolio = portfolio or PortfolioManager()
        self.trades = trades or TradeRepository()
        self._trade_ids: dict[str, int] = {}
        self._state_lock = threading.RLock()

    def load_kill_switch(self) -> bool | None:
        """Read the entry kill state from the same database as paper trades.

        Legacy injected repositories without a database do not support durable
        settings. Actual database failures propagate so the service can lock
        entries rather than silently reset an unreadable kill state.
        """
        database = getattr(self.trades, "db", None)
        if database is None:
            return None
        row = database.fetchone(
            "SELECT value FROM settings WHERE key = ?",
            (self.KILL_SWITCH_SETTING,),
        )
        if row is None:
            return False
        value = row["value"]
        if value not in {"true", "false"}:
            raise ValueError("Stored paper kill-switch state is invalid")
        return value == "true"

    def save_kill_switch(self, enabled: bool) -> bool:
        """Persist the kill state; success means the shared DB committed it."""
        database = getattr(self.trades, "db", None)
        if database is None:
            return False
        database.execute(
            """
            INSERT INTO settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (
                self.KILL_SWITCH_SETTING,
                "true" if enabled else "false",
                datetime.now(self.MARKET_TZ).isoformat(),
            ),
        )
        return True

    @classmethod
    def _market_time(cls, now: datetime) -> time:
        return now.astimezone(cls.MARKET_TZ).time() if now.tzinfo else now.time()

    @classmethod
    def _can_open(cls, now: datetime) -> bool:
        local = now.astimezone(cls.MARKET_TZ) if now.tzinfo else now
        return (
            local.weekday() < 5
            and cls.MARKET_OPEN_TIME <= local.time() < cls.FORCE_EXIT_TIME
        )

    @staticmethod
    def _optional_text(order: Any, name: str, *, lower=False, upper=False):
        value = str(getattr(order, name, "") or "").strip()
        if not value:
            return None
        if lower:
            return value.lower()
        if upper:
            return value.upper()
        return value

    @staticmethod
    def _optional_float(order: Any, name: str):
        value = getattr(order, name, None)
        if value is None:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if isfinite(number) else None

    @staticmethod
    def _finite_level(value: Any, name: str, *, positive: bool = False) -> float:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be a finite number")
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(f"{name} must be a finite number") from None
        if not isfinite(number) or (number <= 0 if positive else number < 0):
            qualifier = "positive" if positive else "non-negative"
            raise ValueError(f"{name} must be finite and {qualifier}")
        return number

    @classmethod
    def _order_values(cls, order: Any) -> tuple[float, int, float, float]:
        price = cls._finite_level(order.price, "entry_price", positive=True)
        quantity = cls._finite_level(order.quantity, "quantity", positive=True)
        if not quantity.is_integer():
            raise ValueError("quantity must be a positive integer")
        if not isfinite(price * quantity):
            raise ValueError("Paper position value must be finite")
        raw_stop = getattr(order, "stoploss", None)
        raw_target = getattr(order, "target2", None)
        stop = cls._finite_level(0.0 if raw_stop is None else raw_stop, "stoploss")
        target = cls._finite_level(0.0 if raw_target is None else raw_target, "target2")
        side = str(getattr(order, "side", "BUY")).strip().upper()
        mode = str(getattr(order, "trade_mode", "intraday") or "intraday").strip().lower()
        if side not in {"BUY", "SELL", "SHORT"}:
            raise ValueError("Paper side must be BUY or SHORT/SELL")
        if side in {"SELL", "SHORT"} and (mode != "intraday" or not 0 < target < price < stop):
            raise ValueError("Short entries require intraday mode and target < entry < stop")
        return price, int(quantity), stop, target

    @classmethod
    def _validate_mark(cls, position: Any, price: float) -> float:
        entry = cls._finite_level(position.average_price, "entry_price", positive=True)
        quantity = cls._finite_level(position.quantity, "quantity", positive=True)
        notional = entry * quantity
        pnl = (price - entry) * quantity
        if (
            not isfinite(notional)
            or notional <= 0
            or not isfinite(price * quantity)
            or not isfinite(pnl)
        ):
            raise ValueError("Paper mark produces non-finite P&L")
        pnl_percent = (pnl / notional) * 100.0
        if not isfinite(pnl_percent):
            raise ValueError("Paper mark produces non-finite P&L")
        return -pnl if position.side in {"SELL", "SHORT"} else pnl

    @staticmethod
    def _finite_total(values) -> float:
        try:
            total = fsum(float(value) for value in values)
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Paper P&L totals must be finite") from None
        if not isfinite(total):
            raise ValueError("Paper P&L totals must be finite")
        return total

    def _pnl_totals(
        self,
        marked_pnls: dict[str, float] | None = None,
        closing: set[str] | None = None,
    ) -> tuple[float, float, float]:
        """Project complete reported balances before any mark or close is saved."""
        marked_pnls = marked_pnls or {}
        closing = closing or set()
        realized_fn = getattr(self.trades, "realized_pnl", None)
        try:
            saved_realized = float(realized_fn()) if callable(realized_fn) else 0.0
        except (TypeError, ValueError, OverflowError):
            raise ValueError("Paper P&L totals must be finite") from None
        realized_values = [saved_realized]
        unrealized_values = []
        for symbol, position in self.portfolio.positions.items():
            pnl = marked_pnls.get(symbol, position.pnl)
            if symbol in closing:
                realized_values.append(pnl)
            else:
                unrealized_values.append(pnl)
        realized = self._finite_total(realized_values)
        unrealized = self._finite_total(unrealized_values)
        total = self._finite_total((realized, unrealized))
        return unrealized, realized, total

    def open(self, order: Any, now: datetime | None = None) -> int:
        with self._state_lock:
            return self._open(order, now=now)

    def _open(self, order: Any, now: datetime | None = None) -> int:
        now = now or datetime.now(self.MARKET_TZ)
        if not self._can_open(now):
            raise ValueError(
                "Paper trading entries are allowed only during NSE market "
                "hours (09:15-15:00 IST, weekdays)"
            )
        symbol = str(order.symbol).upper()
        if symbol in self.portfolio.positions:
            raise ValueError(f"Paper position already open for {symbol}")
        trade_mode = (
            str(getattr(order, "trade_mode", "intraday") or "intraday").strip().lower()
        )
        if trade_mode not in {"intraday", "swing"}:
            raise ValueError("trade_mode must be intraday or swing")

        price, quantity, stop, target = self._order_values(order)
        side = str(order.side).strip().upper()
        if side not in {"BUY", "SELL", "SHORT"}:
            raise ValueError("Paper side must be BUY or SHORT/SELL")
        if side in {"SELL", "SHORT"} and (trade_mode != "intraday" or not 0 < target < price < stop):
            raise ValueError("Short entries require intraday mode and target < entry < stop")
        # A previously corrupted ledger must not gain a new position before
        # the response's accounting snapshot discovers the invalid balances.
        self._pnl_totals()
        values = dict(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=price,
            stoploss=stop,
            target=target,
            status="OPEN",
            created_at=(now.astimezone(self.MARKET_TZ) if now.tzinfo else now.replace(tzinfo=self.MARKET_TZ)).isoformat(),
            trade_mode=trade_mode,
            strategy_id=self._optional_text(order, "strategy_id", lower=True),
            strategy_name=self._optional_text(order, "strategy_name"),
            strategy_source=self._optional_text(order, "strategy_source"),
            source_scan_run_id=self._optional_text(order, "source_scan_run_id"),
            validation_run_id=self._optional_text(order, "validation_run_id"),
            strategy_score=self._optional_float(order, "strategy_score"),
            consensus_score=self._optional_float(order, "consensus_score"),
            entry_signal=self._optional_text(order, "entry_signal", upper=True),
            entry_bar_at=self._optional_text(order, "entry_bar_at"),
        )
        # Use the validated values for both persistence and in-memory marks.
        # Stage portfolio admission before saving. The state lock prevents
        # monitoring/snapshots from seeing an order that is not yet committed.
        try:
            self.portfolio.add(SimpleNamespace(**values, price=price, target2=target))
            trade_id = self.trades.save(**values)
        except Exception:
            self.portfolio.positions.pop(symbol, None)
            raise
        self._trade_ids[symbol] = trade_id
        return trade_id

    def restore_open(self) -> int:
        with self._state_lock:
            return self._restore_open()

    def _restore_open(self) -> int:
        restored = 0
        for raw in self.trades.open_trades():
            row = dict(raw) if not isinstance(raw, dict) else raw
            symbol = str(row["symbol"]).upper()
            if symbol in self.portfolio.positions:
                continue
            trade_mode = (
                str(row.get("trade_mode", "intraday") or "intraday").strip().lower()
            )
            order = SimpleNamespace(
                symbol=symbol,
                side=row["side"],
                quantity=int(row["quantity"]),
                price=float(row["entry_price"]),
                stoploss=float(row["stoploss"] or 0.0),
                target2=float(row["target"] or 0.0),
                trade_mode=trade_mode,
                strategy_id=row.get("strategy_id"),
                strategy_name=row.get("strategy_name"),
                strategy_source=row.get("strategy_source"),
                source_scan_run_id=row.get("source_scan_run_id"),
                validation_run_id=row.get("validation_run_id"),
                strategy_score=float(row.get("strategy_score") or 0.0),
                consensus_score=float(row.get("consensus_score") or 0.0),
                entry_signal=row.get("entry_signal"),
                entry_bar_at=row.get("entry_bar_at"),
                created_at=row.get("created_at"),
            )
            self._order_values(order)
            order.strategy_score = self._optional_float(order, "strategy_score") or 0.0
            order.consensus_score = (
                self._optional_float(order, "consensus_score") or 0.0
            )
            self.portfolio.add(order)
            self._trade_ids[symbol] = int(row["id"])
            restored += 1
        return restored

    @classmethod
    def _exit_reason(
        cls,
        position,
        ltp: float,
        now: datetime,
    ) -> str | None:
        side = str(position.side).upper()
        trade_mode = (
            str(getattr(position, "trade_mode", "intraday") or "intraday")
            .strip()
            .lower()
        )
        if trade_mode != "swing" and cls._market_time(now) >= cls.FORCE_EXIT_TIME:
            return "FORCE_EXIT_15_00_IST"
        entered = getattr(position, "entry_at", None)
        if trade_mode != "swing" and entered:
            entry_stamp = datetime.fromisoformat(entered)
            local = now.astimezone(cls.MARKET_TZ) if now.tzinfo else now
            entry_local = entry_stamp.astimezone(cls.MARKET_TZ) if entry_stamp.tzinfo else entry_stamp
            if entry_local.date() < local.date():
                return "MISSED_INTRADAY_SQUARE_OFF"
        if side in {"SELL", "SHORT"}:
            if position.stoploss and ltp >= position.stoploss:
                return "STOPLOSS"
            if position.target2 and ltp <= position.target2:
                return "TARGET"
        else:
            if position.stoploss and ltp <= position.stoploss:
                return "STOPLOSS"
            if position.target2 and ltp >= position.target2:
                return "TARGET"
        return None

    def _persist_close(
        self,
        trade_id: int | None,
        exit_price: float,
        *,
        exit_reason: str,
        exit_signal: str | None = None,
        exit_signal_at: str | None = None,
        exit_strategy_score: float | None = None,
    ) -> None:
        if trade_id is None:
            return
        method = getattr(self.trades, "close_trade", None)
        if not callable(method):
            return
        try:
            method(
                trade_id,
                exit_price,
                exit_reason=exit_reason,
                exit_signal=exit_signal,
                exit_signal_at=exit_signal_at,
                exit_strategy_score=exit_strategy_score,
            )
        except TypeError:
            # Backward-compatible for repository doubles used by older tests.
            method(trade_id, exit_price)

    @staticmethod
    def _closed_row(
        *,
        trade_id: int | None,
        symbol: str,
        position: Any,
        exit_price: float,
        reason: str,
        exit_signal: str | None = None,
        exit_signal_at: str | None = None,
        exit_strategy_score: float | None = None,
    ) -> dict[str, Any]:
        return {
            "trade_id": trade_id,
            "symbol": symbol,
            "exit_price": exit_price,
            "pnl": position.pnl,
            "reason": reason,
            "strategy_id": getattr(position, "strategy_id", None),
            "strategy_name": getattr(position, "strategy_name", None),
            "strategy_source": getattr(position, "strategy_source", None),
            "source_scan_run_id": getattr(position, "source_scan_run_id", None),
            "validation_run_id": getattr(position, "validation_run_id", None),
            "trade_mode": getattr(position, "trade_mode", None),
            "exit_signal": exit_signal,
            "exit_signal_at": exit_signal_at,
            "exit_strategy_score": exit_strategy_score,
        }

    def monitor(
        self,
        quotes: dict[str, float],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self._state_lock:
            return self._monitor(quotes, now=now)

    def _monitor(
        self,
        quotes: dict[str, float],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        now = now or datetime.now(self.MARKET_TZ)
        # Validate the complete supplied mark set before any position or trade
        # can be changed. One malformed quote must not leave a partial close.
        marks: dict[str, float] = {}
        marked_pnls: dict[str, float] = {}
        reasons: dict[str, str | None] = {}
        for symbol, position in list(self.portfolio.positions.items()):
            if symbol not in quotes:
                continue
            price = self._finite_level(quotes[symbol], "quote price", positive=True)
            marked_pnls[symbol] = self._validate_mark(position, price)
            marks[symbol] = price
            reasons[symbol] = self._exit_reason(position, price, now)
        self._pnl_totals(
            marked_pnls,
            {symbol for symbol, reason in reasons.items() if reason is not None},
        )
        closed = []
        for symbol, position in list(self.portfolio.positions.items()):
            if symbol not in marks:
                continue
            ltp = marks[symbol]
            self.portfolio.update(symbol, ltp)
            reason = reasons[symbol]
            if reason is None:
                continue
            trade_id = self._trade_ids.get(symbol)
            self._persist_close(
                trade_id,
                ltp,
                exit_reason=reason,
            )
            closed.append(
                self._closed_row(
                    trade_id=trade_id,
                    symbol=symbol,
                    position=position,
                    exit_price=ltp,
                    reason=reason,
                )
            )
            self.portfolio.positions.pop(symbol, None)
            self._trade_ids.pop(symbol, None)
        return closed

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
        with self._state_lock:
            return self._close_strategy_exit(
                symbol,
                exit_price,
                exit_signal=exit_signal,
                exit_signal_at=exit_signal_at,
                exit_strategy_score=exit_strategy_score,
                now=now,
            )

    def _close_strategy_exit(
        self,
        symbol: str,
        exit_price: float,
        *,
        exit_signal: str,
        exit_signal_at: str | None = None,
        exit_strategy_score: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        resolved = str(symbol or "").strip().upper()
        if not resolved:
            raise ValueError("symbol is required")
        position = self.portfolio.positions.get(resolved)
        if position is None:
            raise ValueError(f"No open paper position for {resolved}")
        if not getattr(position, "strategy_id", None):
            raise ValueError(f"Paper position {resolved} has no strategy lineage")
        price = self._finite_level(exit_price, "exit_price", positive=True)
        projected_pnl = self._validate_mark(position, price)
        if exit_strategy_score is not None and not isfinite(float(exit_strategy_score)):
            raise ValueError("exit_strategy_score must be finite")
        self._pnl_totals({resolved: projected_pnl}, {resolved})

        current = now or datetime.now(self.MARKET_TZ)
        self.portfolio.update(resolved, price)
        trade_id = self._trade_ids.get(resolved)
        signal_name = str(exit_signal or "EXIT").strip().upper()
        signal_at = (
            str(exit_signal_at or "").strip()
            or current.astimezone(self.MARKET_TZ).isoformat()
        )
        self._persist_close(
            trade_id,
            price,
            exit_reason="STRATEGY_EXIT",
            exit_signal=signal_name,
            exit_signal_at=signal_at,
            exit_strategy_score=exit_strategy_score,
        )
        row = self._closed_row(
            trade_id=trade_id,
            symbol=resolved,
            position=position,
            exit_price=price,
            reason="STRATEGY_EXIT",
            exit_signal=signal_name,
            exit_signal_at=signal_at,
            exit_strategy_score=exit_strategy_score,
        )
        self.portfolio.positions.pop(resolved, None)
        self._trade_ids.pop(resolved, None)
        return row

    def close(self) -> None:
        with self._state_lock:
            closer = getattr(self.trades, "close", None)
            if callable(closer):
                closer()

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            return self._snapshot()

    def _snapshot(self) -> dict[str, Any]:
        unrealized, realized, total = self._pnl_totals()
        return {
            "open_positions": len(self.portfolio.positions),
            "positions": [
                {**dict(vars(p)), "signal": "HOLD"}
                if hasattr(p, "__dict__")
                else {**{n: getattr(p, n) for n in getattr(p, "__slots__", [])}, "signal": "HOLD"}
                for p in self.portfolio.positions.values()
            ],
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": total,
        }


__all__ = ["PaperTradingRuntime"]
