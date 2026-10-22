"""Failed SQLite writes cannot be committed by an unrelated later query."""
import sqlite3

import pytest

from database.database import Database


def test_partial_batch_failure_rolls_back_before_later_reads(tmp_path):
    target = tmp_path / "atomic.db"
    with Database(str(target)) as db:
        db.execute("CREATE TABLE entries (symbol TEXT PRIMARY KEY)")
        db.execute("INSERT INTO entries VALUES (?)", ("EXISTING",))
        with pytest.raises(sqlite3.IntegrityError):
            db.executemany("INSERT INTO entries VALUES (?)", [("NEW",), ("EXISTING",)])
        assert not db.conn.in_transaction
        assert [row["symbol"] for row in db.fetchall("SELECT symbol FROM entries")] == ["EXISTING"]
    with Database(str(target)) as reopened:
        assert [row["symbol"] for row in reopened.fetchall("SELECT symbol FROM entries")] == ["EXISTING"]
