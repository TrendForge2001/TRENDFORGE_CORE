"""Persistent paper-trading runtime with SL, targets and strategy exits."""
from __future__ import annotations

from datetime import datetime, time
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from database.repositories.trade_repository import TradeRepository
from execution.portfolio_manager import PortfolioManager


class PaperTradingRuntime:
    FORCE_EXIT_TIME = time(15, 0)
    MARKET_OPEN_TIME = time(9, 15)
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, portfolio=None, trades=None) -> None:
        self.portfolio = portfolio or PortfolioManager()
        self.trades = trades or TradeRepository()
        self._trade_ids: dict[str, int] = {}

    @classmethod
    def _market_time(cls, now: datetime) -> time:
        return (
            now.astimezone(cls.MARKET_TZ).time()
            if now.tzinfo
            else now.time()
        )

    @classmethod
    def _can_open(cls, now: datetime) -> bool:
        return (
            now.weekday() < 5
            and cls.MARKET_OPEN_TIME
            <= cls._market_time(now)
            < cls.FORCE_EXIT_TIME
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
            return float(value)
        except (TypeError, ValueError):
            return None

    def open(self, order: Any, now: datetime | None = None) -> int:
        now = now or datetime.now(self.MARKET_TZ)
        if not self._can_open(now):
            raise ValueError(
                "Paper trading entries are allowed only during NSE market "
                "hours (09:15-15:00 IST, weekdays)"
            )
        symbol = str(order.symbol).upper()
        if symbol in self.portfolio.positions:
            raise ValueError(f"Paper position already open for {symbol}")
        trade_mode = str(
            getattr(order, "trade_mode", "intraday") or "intraday"
        ).strip().lower()
        if trade_mode not in {"intraday", "swing"}:
            raise ValueError("trade_mode must be intraday or swing")

        trade_id = self.trades.save(
            symbol=symbol,
            side=order.side,
            quantity=order.quantity,
            entry_price=order.price,
            stoploss=getattr(order, "stoploss", None),
            target=getattr(order, "target2", None),
            status="OPEN",
            created_at=now.astimezone(self.MARKET_TZ).isoformat(),
            trade_mode=trade_mode,
            strategy_id=self._optional_text(
                order, "strategy_id", lower=True
            ),
            strategy_name=self._optional_text(order, "strategy_name"),
            strategy_source=self._optional_text(order, "strategy_source"),
            source_scan_run_id=self._optional_text(
                order, "source_scan_run_id"
            ),
            validation_run_id=self._optional_text(
                order, "validation_run_id"
            ),
            strategy_score=self._optional_float(order, "strategy_score"),
            consensus_score=self._optional_float(
                order, "consensus_score"
            ),
            entry_signal=self._optional_text(
                order, "entry_signal", upper=True
            ),
            entry_bar_at=self._optional_text(order, "entry_bar_at"),
        )
        self.portfolio.add(order)
        self._trade_ids[symbol] = trade_id
        return trade_id

    def restore_open(self) -> int:
        restored = 0
        for raw in self.trades.open_trades():
            row = dict(raw) if not isinstance(raw, dict) else raw
            symbol = str(row["symbol"]).upper()
            if symbol in self.portfolio.positions:
                continue
            trade_mode = str(
                row.get("trade_mode", "intraday") or "intraday"
            ).strip().lower()
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
        trade_mode = str(
            getattr(position, "trade_mode", "intraday") or "intraday"
        ).strip().lower()
        if (
            trade_mode != "swing"
            and cls._market_time(now) >= cls.FORCE_EXIT_TIME
        ):
            return "FORCE_EXIT_15_00_IST"
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
            "source_scan_run_id": getattr(
                position, "source_scan_run_id", None
            ),
            "validation_run_id": getattr(
                position, "validation_run_id", None
            ),
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
        now = now or datetime.now(self.MARKET_TZ)
        closed = []
        for symbol, position in list(self.portfolio.positions.items()):
            if symbol not in quotes:
                continue
            ltp = float(quotes[symbol])
            self.portfolio.update(symbol, ltp)
            reason = self._exit_reason(position, ltp, now)
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
        resolved = str(symbol or "").strip().upper()
        if not resolved:
            raise ValueError("symbol is required")
        position = self.portfolio.positions.get(resolved)
        if position is None:
            raise ValueError(
                f"No open paper position for {resolved}"
            )
        if not getattr(position, "strategy_id", None):
            raise ValueError(
                f"Paper position {resolved} has no strategy lineage"
            )
        price = float(exit_price)
        if price <= 0:
            raise ValueError("exit_price must be positive")

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
        closer = getattr(self.trades, "close", None)
        if callable(closer):
            closer()

    def snapshot(self) -> dict[str, Any]:
        unrealized = self.portfolio.total_pnl()
        realized_fn = getattr(self.trades, "realized_pnl", None)
        realized = (
            float(realized_fn())
            if callable(realized_fn)
            else 0.0
        )
        return {
            "open_positions": len(self.portfolio.positions),
            "positions": [
                {
                    name: getattr(position, name)
                    for name in position.__slots__
                }
                for position in self.portfolio.positions.values()
            ],
            "unrealized_pnl": unrealized,
            "realized_pnl": realized,
            "total_pnl": realized + unrealized,
        }


__all__ = ["PaperTradingRuntime"]
