"""Application service for persisted named watchlists."""
from __future__ import annotations

from typing import Any

from database.repositories.watchlist_repository import (
    WatchlistRepository,
)


class WatchlistDashboardService:
    def __init__(
        self,
        repository: WatchlistRepository | None = None,
    ) -> None:
        self._owns_repository = repository is None
        self.repository = repository or WatchlistRepository()

    @staticmethod
    def _name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("watchlist name is required")
        if len(name) > 80:
            raise ValueError(
                "watchlist name must be 80 characters or fewer"
            )
        return name

    @staticmethod
    def _symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if len(symbol) > 30:
            raise ValueError(
                "symbol must be 30 characters or fewer"
            )
        return symbol

    def summary(self) -> dict[str, Any]:
        rows = self.repository.all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            name = str(row.get("watchlist") or "")
            grouped.setdefault(name, []).append(row)

        watchlists = []
        for name in sorted(grouped):
            items = grouped[name]
            priorities = [
                int(item.get("priority") or 0)
                for item in items
            ]
            scores = [
                float(item["score"])
                for item in items
                if item.get("score") is not None
            ]
            watchlists.append(
                {
                    "name": name,
                    "count": len(items),
                    "high_priority": sum(
                        1 for value in priorities
                        if value >= 3
                    ),
                    "average_score": (
                        round(
                            sum(scores) / len(scores),
                            2,
                        )
                        if scores
                        else None
                    ),
                    "symbols": [
                        str(item.get("symbol") or "")
                        for item in items
                    ],
                }
            )

        return {
            "status": "ready",
            "watchlist_count": len(watchlists),
            "symbol_count": len(
                {
                    str(row.get("symbol") or "")
                    for row in rows
                    if row.get("symbol")
                }
            ),
            "entry_count": len(rows),
            "watchlists": watchlists,
        }

    def get(self, name: str) -> dict[str, Any]:
        normalized = self._name(name)
        rows = self.repository.get(normalized)
        return {
            "status": "ready",
            "name": normalized,
            "count": len(rows),
            "symbols": [
                str(row.get("symbol") or "")
                for row in rows
            ],
            "entries": rows,
        }

    def upsert(
        self,
        name: str,
        *,
        symbol: str,
        exchange: str = "NSE",
        notes: str = "",
        priority: int = 1,
        target: float | None = None,
        stoploss: float | None = None,
        scanner: str | None = None,
        score: float | None = None,
        last_signal: str | None = None,
        last_scan: str | None = None,
    ) -> dict[str, Any]:
        normalized = self._name(name)
        ticker = self._symbol(symbol)
        if not 1 <= int(priority) <= 5:
            raise ValueError(
                "priority must be between 1 and 5"
            )
        if target is not None and float(target) < 0:
            raise ValueError("target must be non-negative")
        if stoploss is not None and float(stoploss) < 0:
            raise ValueError("stoploss must be non-negative")

        entry = self.repository.add(
            normalized,
            ticker,
            exchange=exchange,
            notes=notes,
            priority=int(priority),
            target=target,
            stoploss=stoploss,
            scanner=scanner,
            score=score,
            last_signal=last_signal,
            last_scan=last_scan,
        )
        return {
            "status": "saved",
            "watchlist": normalized,
            "entry": entry,
        }

    def update(
        self,
        name: str,
        symbol: str,
        **fields: Any,
    ) -> dict[str, Any]:
        normalized = self._name(name)
        ticker = self._symbol(symbol)
        if not self.repository.exists(
            normalized,
            ticker,
        ):
            raise KeyError(
                f"{ticker} is not in watchlist {normalized}"
            )
        priority = fields.get("priority")
        if priority is not None and not 1 <= int(priority) <= 5:
            raise ValueError(
                "priority must be between 1 and 5"
            )
        entry = self.repository.update(
            normalized,
            ticker,
            **fields,
        )
        return {
            "status": "updated",
            "watchlist": normalized,
            "entry": entry,
        }

    def remove(
        self,
        name: str,
        symbol: str,
    ) -> dict[str, Any]:
        normalized = self._name(name)
        ticker = self._symbol(symbol)
        existed = self.repository.exists(
            normalized,
            ticker,
        )
        self.repository.remove(
            normalized,
            ticker,
        )
        return {
            "status": (
                "removed"
                if existed
                else "not_found"
            ),
            "watchlist": normalized,
            "symbol": ticker,
        }

    def delete(
        self,
        name: str,
    ) -> dict[str, Any]:
        normalized = self._name(name)
        count = len(self.repository.get(normalized))
        self.repository.delete_watchlist(normalized)
        return {
            "status": "deleted",
            "watchlist": normalized,
            "removed_entries": count,
        }

    def close(self) -> None:
        if self._owns_repository:
            self.repository.close()


__all__ = ["WatchlistDashboardService"]
