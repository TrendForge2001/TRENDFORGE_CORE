"""SQLite repository for broker instrument metadata."""
from __future__ import annotations

from database.database import Database


class InstrumentRepository:
    def __init__(
        self,
        db: Database | None = None,
        db_path: str | None = None,
    ):
        self._owns_database = db is None
        self.db = db or Database(db_path)

    def save_all(self, instruments):
        self.db.execute("DELETE FROM instruments")
        rows = []
        for instrument in instruments:
            rows.append(
                (
                    instrument["instrument_token"],
                    instrument["exchange_token"],
                    instrument["tradingsymbol"],
                    instrument["name"],
                    instrument["last_price"],
                    instrument["expiry"],
                    instrument["strike"],
                    instrument["tick_size"],
                    instrument["lot_size"],
                    instrument["instrument_type"],
                    instrument["segment"],
                    instrument["exchange"],
                )
            )
        self.db.executemany(
            """
            INSERT INTO instruments
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )

    def by_symbol(self, symbol, exchange: str | None = None):
        normalized = str(symbol or "").strip().upper()
        if exchange:
            return self.db.fetchone(
                """
                SELECT *
                FROM instruments
                WHERE UPPER(tradingsymbol)=? AND UPPER(exchange)=?
                LIMIT 1
                """,
                (normalized, str(exchange).strip().upper()),
            )
        return self.db.fetchone(
            """
            SELECT *
            FROM instruments
            WHERE UPPER(tradingsymbol)=?
            LIMIT 1
            """,
            (normalized,),
        )

    def exact_name_matches(
        self,
        name: str,
        *,
        exchange: str = "NSE",
        equity_only: bool = True,
    ):
        normalized = " ".join(str(name or "").strip().upper().split())
        if not normalized:
            return []
        query = """
            SELECT *
            FROM instruments
            WHERE UPPER(TRIM(name))=?
              AND UPPER(exchange)=?
        """
        params = [normalized, str(exchange).strip().upper()]
        if equity_only:
            query += """
              AND (
                    UPPER(instrument_type)='EQ'
                    OR UPPER(segment)='NSE'
                  )
            """
        query += " ORDER BY tradingsymbol"
        return [
            dict(row)
            for row in self.db.fetchall(query, tuple(params))
        ]

    def token(self, symbol):
        row = self.by_symbol(symbol)
        return row["instrument_token"] if row else None

    def symbols(self, exchange="NSE"):
        rows = self.db.fetchall(
            """
            SELECT tradingsymbol
            FROM instruments
            WHERE UPPER(exchange)=?
            ORDER BY tradingsymbol
            """,
            (str(exchange).strip().upper(),),
        )
        return [row["tradingsymbol"] for row in rows]

    def close(self) -> None:
        if self._owns_database:
            self.db.close()


__all__ = ["InstrumentRepository"]
