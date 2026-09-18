"""Live portfolio synchronization from Zerodha Kite to the local portfolio store."""
from __future__ import annotations

from typing import Any

from database.repositories.portfolio_repository import PortfolioRepository


class LivePortfolioSyncService:
    """Synchronize broker holdings/positions without placing orders."""

    def __init__(self, broker: Any, repository: PortfolioRepository | None = None) -> None:
        if broker is None:
            raise ValueError("broker is required")
        self.broker = broker
        self.repository = repository or PortfolioRepository()

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return list(value.values()) if value else []
        return [dict(item) for item in (value or [])]

    @staticmethod
    def _holding(row: dict[str, Any]) -> dict[str, Any]:
        quantity = int(row.get("quantity") or 0)
        average = float(row.get("average_price") or row.get("average_price") or 0.0)
        ltp = float(row.get("last_price") or row.get("ltp") or 0.0)
        return {
            "symbol": str(row.get("tradingsymbol") or row.get("symbol") or "").upper(),
            "exchange": str(row.get("exchange") or "NSE"),
            "sector": row.get("sector"),
            "quantity": quantity,
            "average_price": average,
            "ltp": ltp,
        }

    def sync(self) -> dict[str, Any]:
        holdings = [self._holding(row) for row in self._rows(self.broker.holdings())]
        positions = [self._holding(row) for row in self._rows(self.broker.positions())]

        merged: dict[str, dict[str, Any]] = {}
        for row in holdings + positions:
            symbol = row["symbol"]
            if not symbol:
                continue
            existing = merged.get(symbol)
            if existing is None:
                merged[symbol] = row
                continue
            qty_a, qty_b = existing["quantity"], row["quantity"]
            total_qty = qty_a + qty_b
            if total_qty:
                existing["average_price"] = (
                    existing["average_price"] * qty_a + row["average_price"] * qty_b
                ) / total_qty
            existing["quantity"] = total_qty
            if row["ltp"]:
                existing["ltp"] = row["ltp"]

        self.repository.save_many(list(merged.values()))
        return {
            "status": "synced",
            "count": len(merged),
            "portfolio_value": self.repository.portfolio_value(),
            "investment": self.repository.investment(),
            "total_pnl": self.repository.total_pnl(),
        }

    def snapshot(self) -> dict[str, Any]:
        rows = [dict(row) for row in self.repository.all()]
        return {
            "count": len(rows),
            "holdings": rows,
            "portfolio_value": self.repository.portfolio_value(),
            "investment": self.repository.investment(),
            "total_pnl": self.repository.total_pnl(),
        }
