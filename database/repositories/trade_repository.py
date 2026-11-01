"""
TrendForge
Trade Repository
"""

from datetime import datetime
from zoneinfo import ZoneInfo
import json

from database.database import Database


class TradeRepository:
    MARKET_TZ = ZoneInfo("Asia/Kolkata")

    def __init__(self, db=None):
        self._owns_database = db is None
        self.db = db or Database()

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
        created_at=None,
        trade_mode="intraday",
        strategy_id=None,
        strategy_name=None,
        strategy_source=None,
        source_scan_run_id=None,
        validation_run_id=None,
        strategy_score=None,
        consensus_score=None,
        entry_signal=None,
        entry_bar_at=None,
        paper_plan=None,
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
                created_at,
                trade_mode,
                strategy_id,
                strategy_name,
                strategy_source,
                source_scan_run_id,
                validation_run_id,
                strategy_score,
                consensus_score,
                entry_signal,
                entry_bar_at,
                paper_plan_json
            )
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                created_at or datetime.now(self.MARKET_TZ).isoformat(),
                str(trade_mode or "intraday").strip().lower(),
                str(strategy_id or "").strip().lower() or None,
                str(strategy_name or "").strip() or None,
                str(strategy_source or "").strip() or None,
                str(source_scan_run_id or "").strip() or None,
                str(validation_run_id or "").strip() or None,
                float(strategy_score) if strategy_score is not None else None,
                float(consensus_score) if consensus_score is not None else None,
                str(entry_signal or "").strip().upper() or None,
                str(entry_bar_at or "").strip() or None,
                json.dumps(paper_plan, allow_nan=False)
                if paper_plan is not None
                else None,
            ),
        )
        return self.db.fetchone("SELECT last_insert_rowid() AS id")["id"]

    def close_trade(
        self,
        trade_id,
        exit_price,
        *,
        exit_reason=None,
        exit_signal=None,
        exit_signal_at=None,
        exit_strategy_score=None,
        closed_at=None,
    ):
        trade = self.get(trade_id)
        if trade is None:
            return

        qty = trade["quantity"]
        if trade["side"] == "BUY":
            pnl = (exit_price - trade["entry_price"]) * qty
        else:
            pnl = (trade["entry_price"] - exit_price) * qty

        closed_at = closed_at or datetime.now(self.MARKET_TZ).isoformat()
        self.db.execute(
            """
            UPDATE trade_history
            SET exit_price=?,
                pnl=?,
                status='CLOSED',
                closed_at=?,
                exit_reason=?,
                exit_signal=?,
                exit_signal_at=?,
                exit_strategy_score=?
            WHERE id=? AND status='OPEN'
            """,
            (
                exit_price,
                pnl,
                closed_at,
                str(exit_reason or "").strip().upper() or None,
                str(exit_signal or "").strip().upper() or None,
                str(exit_signal_at or "").strip() or None,
                (
                    float(exit_strategy_score)
                    if exit_strategy_score is not None
                    else None
                ),
                trade_id,
            ),
        )

    def update_paper_plan(self, trade_id, plan, stoploss):
        changed = self.db.execute(
            "UPDATE trade_history SET paper_plan_json=?, stoploss=? WHERE id=? AND status='OPEN'",
            (json.dumps(plan, allow_nan=False), stoploss, trade_id),
        ).rowcount
        if changed != 1:
            raise ValueError("Staged paper position is no longer open")

    def partial_close(self, trade_id, price, quantity, *, plan, stoploss, closed_at):
        """Commit the exit leg and remaining position together, or neither."""
        with self.db._lock:
            connection = self.db.conn
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM trade_history WHERE id=? AND status='OPEN'",
                    (trade_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("Paper position is no longer open")
                row = dict(row)
                saved = json.loads(row["paper_plan_json"])
                if saved.get("partial_taken"):
                    connection.rollback()
                    return None
                if (
                    not 0 < quantity < row["quantity"]
                    or quantity != row["quantity"] // 2
                ):
                    raise ValueError("Invalid partial paper quantity")
                direction = 1 if row["side"] == "BUY" else -1
                pnl = direction * (price - row["entry_price"]) * quantity
                fields = [
                    "symbol",
                    "side",
                    "entry_price",
                    "stoploss",
                    "target",
                    "created_at",
                    "trade_mode",
                    "strategy_id",
                    "strategy_name",
                    "strategy_source",
                    "source_scan_run_id",
                    "validation_run_id",
                    "strategy_score",
                    "consensus_score",
                    "entry_signal",
                    "entry_bar_at",
                ]
                child = {name: row[name] for name in fields}
                child.update(
                    quantity=quantity,
                    exit_price=price,
                    pnl=pnl,
                    status="CLOSED",
                    closed_at=closed_at,
                    exit_reason="PARTIAL_PROFIT",
                    parent_trade_id=trade_id,
                )
                columns = list(child)
                cursor = connection.execute(
                    f"INSERT INTO trade_history ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(child.values()),
                )
                connection.execute(
                    "UPDATE trade_history SET quantity=?,stoploss=?,paper_plan_json=? WHERE id=?",
                    (
                        row["quantity"] - quantity,
                        stoploss,
                        json.dumps(plan, allow_nan=False),
                        trade_id,
                    ),
                )
                connection.commit()
                return {
                    "trade_id": cursor.lastrowid,
                    "parent_trade_id": trade_id,
                    "pnl": pnl,
                    "quantity": quantity,
                    "symbol": row["symbol"],
                    "exit_price": price,
                    "reason": "PARTIAL_PROFIT",
                    "strategy_id": row["strategy_id"],
                    "closed_at": closed_at,
                }
            except Exception:
                connection.rollback()
                raise

    def get(self, trade_id):
        return self.db.fetchone(
            """
            SELECT *
            FROM trade_history
            WHERE id=?
            """,
            (trade_id,),
        )

    def open_trades(self):
        return self.db.fetchall(
            """
            SELECT *
            FROM trade_history
            WHERE status='OPEN'
            ORDER BY created_at DESC
            """
        )

    def closed_trades(self):
        return self.db.fetchall(
            """
            SELECT *
            FROM trade_history
            WHERE status='CLOSED'
            ORDER BY created_at DESC
            """
        )

    def by_symbol(self, symbol):
        return self.db.fetchall(
            """
            SELECT *
            FROM trade_history
            WHERE symbol=?
            ORDER BY created_at DESC
            """,
            (symbol,),
        )

    def strategy_trades(
        self,
        strategy_id=None,
        *,
        limit=200,
    ):
        value = max(1, min(1000, int(limit)))
        key = str(strategy_id or "").strip().lower()
        if key:
            rows = self.db.fetchall(
                """
                SELECT *
                FROM trade_history
                WHERE strategy_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (key, value),
            )
        else:
            rows = self.db.fetchall(
                """
                SELECT *
                FROM trade_history
                WHERE strategy_id IS NOT NULL
                  AND trim(strategy_id) <> ''
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (value,),
            )
        return [dict(row) for row in rows]

    def strategy_performance(self):
        rows = self.db.fetchall(
            """
            SELECT
                strategy_id,
                MAX(strategy_name) AS strategy_name,
                MAX(strategy_source) AS strategy_source,
                trade_mode,
                COUNT(*) AS closed_trades,
                SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END) AS losses,
                COALESCE(SUM(pnl), 0) AS net_pnl,
                COALESCE(AVG(pnl), 0) AS average_pnl,
                COALESCE(
                    100.0 * SUM(pnl)
                    / NULLIF(SUM(entry_price * quantity), 0),
                    0
                ) AS return_on_entry_notional_pct,
                COALESCE(
                    100.0 * SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0),
                    0
                ) AS win_rate_pct,
                MIN(created_at) AS first_entry_at,
                MAX(closed_at) AS last_exit_at
            FROM trade_history
            WHERE status='CLOSED'
              AND strategy_id IS NOT NULL
              AND trim(strategy_id) <> ''
            GROUP BY strategy_id, trade_mode
            ORDER BY net_pnl DESC, closed_trades DESC
            """
        )
        output = []
        for raw in rows:
            row = dict(raw)
            for key in (
                "net_pnl",
                "average_pnl",
                "return_on_entry_notional_pct",
                "win_rate_pct",
            ):
                row[key] = round(float(row.get(key) or 0.0), 2)
            for key in ("closed_trades", "wins", "losses"):
                row[key] = int(row.get(key) or 0)
            output.append(row)
        return output

    def total_pnl(self):
        row = self.db.fetchone(
            """
            SELECT SUM(pnl) total
            FROM trade_history
            """
        )
        return row["total"] or 0

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
        return round(wins * 100 / total, 2)

    def realized_pnl(self):
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(pnl),0) total FROM trade_history WHERE status='CLOSED'"
        )
        return float(row["total"])

    def realized_pnl_for_entry_date(self, entry_date):
        row = self.db.fetchone(
            """
            SELECT COALESCE(SUM(pnl), 0) total
            FROM trade_history
            WHERE status='CLOSED'
              AND substr(created_at, 1, 10)=?
            """,
            (str(entry_date),),
        )
        return float(row["total"] or 0)

    def realized_pnl_for_date(self, date_text):
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(pnl),0) total FROM trade_history WHERE status='CLOSED' AND substr(COALESCE(closed_at,created_at),1,10)=?",
            (str(date_text),),
        )
        return float(row["total"] or 0)

    def realized_loss_for_date(self, date_text):
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(CASE WHEN pnl<0 THEN -pnl ELSE 0 END),0) total FROM trade_history WHERE status='CLOSED' AND substr(COALESCE(closed_at,created_at),1,10)=?",
            (str(date_text),),
        )
        return float(row["total"] or 0)

    def realized_loss_for_entry_date(self, entry_date):
        row = self.db.fetchone(
            """
            SELECT COALESCE(
                SUM(
                    CASE
                        WHEN pnl < 0 THEN -pnl
                        ELSE 0
                    END
                ),
                0
            ) total
            FROM trade_history
            WHERE status='CLOSED'
              AND substr(created_at, 1, 10)=?
            """,
            (str(entry_date),),
        )
        return float(row["total"] or 0)

    def has_trade_on_entry_date(self, symbol, entry_date):
        row = self.db.fetchone(
            """
            SELECT COUNT(*) total
            FROM trade_history
            WHERE symbol=?
              AND substr(created_at, 1, 10)=?
            """,
            (
                str(symbol).upper(),
                str(entry_date),
            ),
        )
        return bool(int(row["total"] or 0))

    def close(self):
        if self._owns_database:
            self.db.close()

    def clear(self):
        self.db.execute("DELETE FROM trade_history")

    def count(self):
        row = self.db.fetchone("SELECT COUNT(*) total FROM trade_history")
        return row["total"]
