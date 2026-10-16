"""SQLite persistence for named TrendForge watchlists."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from database.database import Database


class WatchlistRepository:
    def __init__(
        self,
        db: Database | None = None,
        db_path: str | None = None,
    ) -> None:
        self._owns_database = db is None
        self.db = db or Database(db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    @staticmethod
    def _name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("watchlist name is required")
        return name

    @staticmethod
    def _symbol(value: Any) -> str:
        symbol = str(value or "").strip().upper()
        if not symbol:
            raise ValueError("watchlist symbol is required")
        return symbol

    def add(
        self,
        watchlist,
        symbol,
        exchange="NSE",
        notes="",
        priority=1,
        target=None,
        stoploss=None,
        scanner=None,
        score=None,
        last_signal=None,
        last_scan=None,
    ):
        name = self._name(watchlist)
        ticker = self._symbol(symbol)

        if self.exists(name, ticker):
            self.update(
                name,
                ticker,
                notes=notes,
                priority=priority,
                target=target,
                stoploss=stoploss,
                scanner=scanner,
                score=score,
                last_signal=last_signal,
                last_scan=last_scan,
            )
            return self.find(name, ticker)

        self.db.execute(
            """
            INSERT INTO watchlists(
                watchlist,
                symbol,
                exchange,
                notes,
                priority,
                target,
                stoploss,
                scanner,
                score,
                last_signal,
                last_scan,
                created_at
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                name,
                ticker,
                str(exchange or "NSE").strip().upper(),
                str(notes or ""),
                int(priority or 1),
                target,
                stoploss,
                scanner,
                score,
                last_signal,
                last_scan,
                self._now(),
            ),
        )
        return self.find(name, ticker)

    def update(
        self,
        watchlist,
        symbol,
        *,
        notes=None,
        priority=None,
        target=None,
        stoploss=None,
        scanner=None,
        score=None,
        last_signal=None,
        last_scan=None,
    ):
        name = self._name(watchlist)
        ticker = self._symbol(symbol)

        fields: list[str] = []
        values: list[Any] = []

        for column, value in (
            ("notes", notes),
            ("priority", priority),
            ("target", target),
            ("stoploss", stoploss),
            ("scanner", scanner),
            ("score", score),
            ("last_signal", last_signal),
            ("last_scan", last_scan),
        ):
            if value is not None:
                fields.append(f"{column}=?")
                values.append(value)

        if not fields:
            return self.find(name, ticker)

        values.extend([name, ticker])
        self.db.execute(
            f"""
            UPDATE watchlists
            SET {', '.join(fields)}
            WHERE watchlist=? AND symbol=?
            """,
            tuple(values),
        )
        return self.find(name, ticker)

    def remove(self, watchlist, symbol) -> None:
        self.db.execute(
            """
            DELETE FROM watchlists
            WHERE watchlist=? AND symbol=?
            """,
            (
                self._name(watchlist),
                self._symbol(symbol),
            ),
        )

    def find(
        self,
        watchlist,
        symbol,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            """
            SELECT *
            FROM watchlists
            WHERE watchlist=? AND symbol=?
            """,
            (
                self._name(watchlist),
                self._symbol(symbol),
            ),
        )
        return dict(row) if row is not None else None

    def get(self, watchlist):
        rows = self.db.fetchall(
            """
            SELECT *
            FROM watchlists
            WHERE watchlist=?
            ORDER BY priority DESC, symbol
            """,
            (self._name(watchlist),),
        )
        return [dict(row) for row in rows]

    def all(self):
        rows = self.db.fetchall(
            """
            SELECT *
            FROM watchlists
            ORDER BY watchlist, priority DESC, symbol
            """
        )
        return [dict(row) for row in rows]

    def watchlists(self):
        rows = self.db.fetchall(
            """
            SELECT DISTINCT watchlist
            FROM watchlists
            ORDER BY watchlist
            """
        )
        return [
            str(row["watchlist"])
            for row in rows
        ]

    def get_all_watchlists(self):
        return self.all()

    def exists(self, watchlist, symbol):
        row = self.db.fetchone(
            """
            SELECT COUNT(*) total
            FROM watchlists
            WHERE watchlist=? AND symbol=?
            """,
            (
                self._name(watchlist),
                self._symbol(symbol),
            ),
        )
        return bool(int(row["total"] or 0))

    def symbols(self, watchlist):
        return [
            row["symbol"]
            for row in self.get(watchlist)
        ]

    def delete_watchlist(self, watchlist) -> None:
        self.db.execute(
            """
            DELETE FROM watchlists
            WHERE watchlist=?
            """,
            (self._name(watchlist),),
        )

    def clear(self) -> None:
        self.db.execute("DELETE FROM watchlists")

    def count(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) total FROM watchlists"
        )
        return int(row["total"] or 0)

    def add_stock(
        self,
        watchlist,
        symbol,
        **kwargs,
    ):
        return self.add(
            watchlist,
            symbol,
            **kwargs,
        )

    def remove_stock(self, watchlist, symbol) -> None:
        self.remove(watchlist, symbol)

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["WatchlistRepository"]
