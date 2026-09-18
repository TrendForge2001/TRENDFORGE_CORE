"""Read-only broker synchronization with separate delivery and trading books."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from database.repositories.live_portfolio_repository import LivePortfolioRepository

class LivePortfolioSyncService:
    def __init__(self, broker: Any, repository: LivePortfolioRepository | None = None) -> None:
        if broker is None: raise ValueError("broker is required")
        self.broker = broker
        self.repository = repository or LivePortfolioRepository()

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict): return [dict(item) for item in value.values()]
        return [dict(item) for item in (value or [])]

    @staticmethod
    def _normalize(row: dict[str, Any], book: str) -> dict[str, Any]:
        return {
            "symbol": str(row.get("tradingsymbol") or row.get("symbol") or "").upper(),
            "exchange": str(row.get("exchange") or "NSE"), "sector": row.get("sector"),
            "book": book, "product": row.get("product"), "quantity": int(row.get("quantity") or 0),
            "average_price": float(row.get("average_price") or 0.0),
            "ltp": float(row.get("last_price") or row.get("ltp") or 0.0),
        }

    def sync(self) -> dict[str, Any]:
        holdings = [self._normalize(r, "HOLDING") for r in self._rows(self.broker.holdings())]
        positions = [self._normalize(r, "POSITION") for r in self._rows(self.broker.positions())]
        rows = [r for r in holdings + positions if r["symbol"] and r["quantity"] != 0]
        self.repository.replace_all(rows)
        return {
            "status": "synced", "count": len(rows), "synced_at": datetime.now(timezone.utc).isoformat(),
            "portfolio_value": self.repository.portfolio_value(), "investment": self.repository.investment(),
            "total_pnl": self.repository.total_pnl(),
            "holdings": [dict(r) for r in self.repository.by_book("HOLDING")],
            "positions": [dict(r) for r in self.repository.by_book("POSITION")],
        }

    def snapshot(self):
        rows = [dict(r) for r in self.repository.all()]
        return {
            "count": len(rows), "holdings": [r for r in rows if r["book"] == "HOLDING"],
            "positions": [r for r in rows if r["book"] == "POSITION"],
            "portfolio_value": self.repository.portfolio_value(), "investment": self.repository.investment(),
            "total_pnl": self.repository.total_pnl(),
        }
