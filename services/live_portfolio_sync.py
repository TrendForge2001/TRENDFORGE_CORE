"""Live portfolio synchronization from Zerodha Kite to the local portfolio store."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from database.repositories.portfolio_repository import PortfolioRepository


class LivePortfolioSyncService:
    """Read broker holdings and net positions without placing orders."""

    def __init__(self, broker: Any, repository: PortfolioRepository | None = None) -> None:
        if broker is None:
            raise ValueError("broker is required")
        self.broker = broker
        self.repository = repository or PortfolioRepository()

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [dict(item) for item in value.values()]
        return [dict(item) for item in (value or [])]

    @staticmethod
    def _holding(row: dict[str, Any]) -> dict[str, Any]:
        quantity = int(row.get("quantity") or 0)
        average = float(row.get("average_price") or 0.0)
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
        # Kite holdings are the delivery book; net positions are the current
        # trading book. They must not be added together: the same symbol can
        # legitimately appear in both books.
        holdings = [self._holding(row) for row in self._rows(self.broker.holdings())]
        positions = [self._holding(row) for row in self._rows(self.broker.positions())]

        rows: list[dict[str, Any]] = []
        rows.extend(row for row in holdings if row["symbol"] and row["quantity"] != 0)
        rows.extend(row for row in positions if row["symbol"] and row["quantity"] != 0)

        # The portfolio table is keyed only by symbol, so combine duplicate
        # books using signed quantities and a weighted average cost.
        merged: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = row["symbol"]
            current = merged.get(symbol)
            if current is None:
                merged[symbol] = row.copy()
                continue
            q1, q2 = current["quantity"], row["quantity"]
            total = q1 + q2
            if total:
                current["average_price"] = (
                    current["average_price"] * q1 + row["average_price"] * q2
                ) / total
            current["quantity"] = total
            if row["ltp"]:
                current["ltp"] = row["ltp"]

        final_rows = [row for row in merged.values() if row["quantity"] != 0]
        self.repository.clear()
        self.repository.save_many(final_rows)
        return {
            "status": "synced",
            "count": len(final_rows),
            "synced_at": datetime.now(timezone.utc).isoformat(),
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
