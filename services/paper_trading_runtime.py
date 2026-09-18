"""Persistent paper-trading runtime with SL, targets and 3 PM force exit."""
from __future__ import annotations

from datetime import datetime, time
from typing import Any

from database.repositories.trade_repository import TradeRepository
from execution.portfolio_manager import PortfolioManager


class PaperTradingRuntime:
    """Manage virtual positions without calling broker order APIs."""

    FORCE_EXIT_TIME = time(15, 0)

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

    @staticmethod
    def _exit_reason(position, ltp: float, now: datetime) -> str | None:
        side = str(position.side).upper()
        if now.time() >= PaperTradingRuntime.FORCE_EXIT_TIME:
            return "FORCE_EXIT_15_00"
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
        now = now or datetime.now()
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
                vars(position) if not hasattr(position, "__slots__") else {
                    name: getattr(position, name)
                    for name in position.__slots__
                }
                for position in self.portfolio.positions.values()
            ],
            "unrealized_pnl": self.portfolio.total_pnl(),
        }


__all__ = ["PaperTradingRuntime"]
