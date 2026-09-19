"""
TrendForge
Trade Repository
"""

from datetime import datetime

from database.database import Database


class TradeRepository:

    def __init__(self):

        self.db = Database()

    # =====================================================
    # Save Trade
    # =====================================================

    def save(
        self,
        symbol,
        side,
        quantity,
        entry_price,
        stoploss=None,
        target=None,
        broker_order_id=None,
        status="OPEN",
    ):

        self.db.execute(
            """
            INSERT INTO trade_history(

                symbol,
                side,
                quantity,
                entry_price,
                stoploss,
                target,
                status,
                broker_order_id,
                created_at

            )

            VALUES(?,?,?,?,?,?,?,?,?)

            """,
            (
                symbol,
                side,
                quantity,
                entry_price,
                stoploss,
                target,
                status,
                broker_order_id,
                datetime.now(),
            ),
        )
        return self.db.fetchone("SELECT last_insert_rowid() AS id")["id"]

    # =====================================================
    # Close Trade
    # =====================================================

    def close_trade(
        self,
        trade_id,
        exit_price,
    ):

        trade = self.get(trade_id)

        if trade is None:
            return

        qty = trade["quantity"]

        if trade["side"] == "BUY":
            pnl = (exit_price - trade["entry_price"]) * qty
        else:
            pnl = (trade["entry_price"] - exit_price) * qty

        self.db.execute(
            """
            UPDATE trade_history

            SET exit_price=?,
                pnl=?,
                status='CLOSED'

            WHERE id=?

            """,
            (
                exit_price,
                pnl,
                trade_id,
            ),
        )

    # =====================================================
    # Get Trade
    # =====================================================

    def get(
        self,
        trade_id,
    ):

        return self.db.fetchone(
            """
            SELECT *

            FROM trade_history

            WHERE id=?

            """,
            (trade_id,),
        )

    # =====================================================
    # Open Trades
    # =====================================================

    def open_trades(self):

        return self.db.fetchall(
            """
            SELECT *

            FROM trade_history

            WHERE status='OPEN'

            ORDER BY created_at DESC
            """
        )

    # =====================================================
    # Closed Trades
    # =====================================================

    def closed_trades(self):

        return self.db.fetchall(
            """
            SELECT *

            FROM trade_history

            WHERE status='CLOSED'

            ORDER BY created_at DESC
            """
        )

    # =====================================================
    # Trades By Symbol
    # =====================================================

    def by_symbol(
        self,
        symbol,
    ):

        return self.db.fetchall(
            """
            SELECT *

            FROM trade_history

            WHERE symbol=?

            ORDER BY created_at DESC
            """,
            (symbol,),
        )

    # =====================================================
    # Total P&L
    # =====================================================

    def total_pnl(self):

        row = self.db.fetchone(
            """
            SELECT SUM(pnl) total

            FROM trade_history
            """
        )

        return row["total"] or 0

    # =====================================================
    # Win Rate
    # =====================================================

    def win_rate(self):

        total = self.db.fetchone(
            """
            SELECT COUNT(*) total

            FROM trade_history

            WHERE status='CLOSED'
            """
        )["total"]

        if total == 0:
            return 0

        wins = self.db.fetchone(
            """
            SELECT COUNT(*) total

            FROM trade_history

            WHERE pnl > 0
            """
        )["total"]

        return round(
            wins * 100 / total,
            2,
        )

    def realized_pnl(self):
        row = self.db.fetchone("""SELECT COALESCE(SUM(pnl),0) total FROM trade_history WHERE status='CLOSED'""")
        return float(row["total"])

    def close(self):
        self.db.close()

    # =====================================================
    # Delete All
    # =====================================================

    def clear(self):

        self.db.execute(
            """
            DELETE FROM trade_history
            """
        )

    # =====================================================
    # Count
    # =====================================================

    def count(self):

        row = self.db.fetchone(
            """
            SELECT COUNT(*) total

            FROM trade_history
            """
        )

        return row["total"]