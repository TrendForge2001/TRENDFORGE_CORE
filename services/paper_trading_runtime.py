"""Persistent paper-trading runtime with SL, targets and 3 PM IST force exit."""
from __future__ import annotations

from datetime import datetime, time
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from database.repositories.trade_repository import TradeRepository
from execution.portfolio_manager import PortfolioManager


class PaperTradingRuntime:
    """Manage virtual positions without calling broker order APIs."""

    FORCE_EXIT_TIME = time(15, 0)
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, portfolio=None, trades=None) -> None:
        self.portfolio = portfolio or PortfolioManager()
        self.trades = trades or TradeRepository()
        self._trade_ids: dict[str, int] = {}

    def open(self, order: Any) -> int:
        trade_id = self.trades.save(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            entry_price=order.price,
            stoploss=getattr(order, "stoploss", None),
            target=getattr(order, "target2", None),
            status="OPEN",
        )
        self.portfolio.add(order)
        self._trade_ids[order.symbol] = trade_id
        return trade_id

    def restore_open(self) -> int:
        """Restore persisted OPEN trades after a process restart."""
        rows = self.trades.open_trades()
        restored = 0
        for row in rows:
            symbol = str(row["symbol"]).upper()
            order = SimpleNamespace(
                symbol=symbol,
                side=row["side"],
                quantity=int(row["quantity"]),
                price=float(row["entry_price"]),
                stoploss=float(row["stoploss"] or 0.0),
                target2=float(row["target"] or 0.0),
            )
            self.portfolio.add(order)
            self._trade_ids[symbol] = int(row["id"])
            restored += 1
        return restored

    @classmethod
    def _market_time(cls, now: datetime) -> time:
        if now.tzinfo is None:
            return now.time()
        return now.astimezone(cls.MARKET_TZ).time()

    @classmethod
    def _exit_reason(cls, position, ltp: float, now: datetime) -> str | None:
        side = str(position.side).upper()
        if cls._market_time(now) >= cls.FORCE_EXIT_TIME:
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

    def monitor(self, quotes: dict[str, float], now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or datetime.now(self.MARKET_TZ)
        closed: list[dict[str, Any]] = []
        for symbol, position in list(self.portfolio.positions.items()):
            if symbol not in quotes:
                continue
            ltp = float(quotes[symbol])
            self.portfolio.update(symbol, ltp)
            reason = self._exit_reason(position, ltp, now)
            if reason is None:
                continue
            trade_id = self._trade_ids.get(symbol)
            if trade_id is not None:
                self.trades.close_trade(trade_id, ltp)
            closed.append({
                "symbol": symbol,
                "exit_price": ltp,
                "pnl": position.pnl,
                "reason": reason,
            })
            self.portfolio.positions.pop(symbol, None)
            self._trade_ids.pop(symbol, None)
        return closed

    def snapshot(self) -> dict[str, Any]:
        return {
            "open_positions": len(self.portfolio.positions),
            "positions": [
                {name: getattr(position, name) for name in position.__slots__}
                for position in self.portfolio.positions.values()
            ],
            "unrealized_pnl": self.portfolio.total_pnl(),
        }


__all__ = ["PaperTradingRuntime"]
