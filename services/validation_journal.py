"""Private, atomic stock/mode checkpoints and streamed validation evidence."""

import gzip
import hashlib
import json
import os
import sqlite3
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.storage_config import resolve_storage

KINDS = ("backtests", "trades", "errors")


def row_bytes(payload):
    """Lossless legacy TEXT or compressed BLOB; no result recalculation."""
    return (
        zlib.decompress(payload)
        if isinstance(payload, bytes)
        else payload.encode("utf-8")
    )


def decode_rows(payload):
    return json.loads(row_bytes(payload))


def encode_rows(rows):
    return zlib.compress(
        json.dumps(rows, separators=(",", ":"), default=str, allow_nan=False).encode(
            "utf-8"
        )
    )


TRADE_FIELDS = (
    "symbol",
    "mode",
    "strategy_id",
    "strategy_name",
    "source",
    "period",
    "interval",
    "membership",
    "trade_number",
    "side",
    "entry_at",
    "entry_signal_at",
    "exit_at",
    "quantity",
    "entry_price",
    "entry_raw_price",
    "exit_price",
    "final_exit_price",
    "exit_reason",
    "gross_pnl",
    "transaction_costs",
    "net_pnl",
    "stoploss",
    "initial_stoploss",
    "target",
    "partial_target",
    "second_target",
    "partial_taken",
    "score",
    "risk_per_share",
    "reward_risk",
    "risk_reward",
    "risk_budget",
    "planned_initial_risk",
    "stop_is_resting_order",
    "sizing_reference_is_conditional",
)
FILL_FIELDS = (
    "quantity",
    "entry_price",
    "exit_price",
    "entry_at",
    "exit_at",
    "side",
    "exit_reason",
    "gross_pnl",
    "transaction_costs",
    "net_pnl",
)


def compact_trade(trade, indicator_keys=()):
    """Keep economic/indicator evidence once, excluding duplicated plan/frame state."""
    result = {key: trade[key] for key in TRADE_FIELDS if key in trade}
    if trade.get("exit_legs"):
        result["exit_legs"] = [
            {k: leg[k] for k in FILL_FIELDS if k in leg} for leg in trade["exit_legs"]
        ]
    source = trade.get("indicators") or {}
    if source:
        result["indicators"] = {k: source[k] for k in indicator_keys if k in source}
    if trade.get("technical_evidence"):
        result["technical_evidence"] = trade["technical_evidence"]
    return result


class JournalRows(Iterable):
    """Only the active stock's rows live in memory; committed rows stream from disk."""

    def __init__(self, journal, kind):
        self.journal, self.kind, self.pending = journal, kind, []

    def append(self, row):
        self.pending.append(row)

    def __iter__(self):
        for row in self.journal.connection.execute(
            f"SELECT {self.kind} FROM units ORDER BY rowid"
        ):
            yield from decode_rows(row[0])
        yield from self.pending

    def __len__(self):
        saved = self.journal.connection.execute(
            f"SELECT COALESCE(SUM({self.kind}_count),0) FROM units"
        ).fetchone()[0]
        return saved + len(self.pending)


class ValidationJournal:
    VERSION = 1

    @staticmethod
    def recent(as_of):
        try:
            stamp = datetime.fromisoformat(as_of)
            return stamp.tzinfo is not None and timedelta(0) <= datetime.now(
                UTC
            ) - stamp <= timedelta(days=7)
        except (TypeError, ValueError):
            return False

    def __init__(self, run_id, request, registry_version, *, root=None, fresh=False):
        root = (
            Path(root)
            if root is not None
            else resolve_storage().database.resolve().parent / "validation"
        )
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / (hashlib.sha256(run_id.encode()).hexdigest() + ".sqlite")
        self.connection = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS meta "
            "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.connection.execute("""CREATE TABLE IF NOT EXISTS units (
            mode TEXT NOT NULL, symbol TEXT NOT NULL,
            backtests TEXT NOT NULL, trades TEXT NOT NULL, errors TEXT NOT NULL,
            backtests_count INTEGER NOT NULL, trades_count INTEGER NOT NULL,
            errors_count INTEGER NOT NULL,
            PRIMARY KEY(mode,symbol))""")
        existing = self.connection.execute(
            "SELECT payload FROM meta WHERE id=1"
        ).fetchone()
        if existing and fresh:
            self.close()
            raise ValueError("Forced validation requires an unused run ID")
        if existing:
            self.metadata = json.loads(existing[0])
            if (
                self.metadata.get("request") != request
                or self.metadata.get("registry_version") != registry_version
                or self.metadata.get("version") != self.VERSION
            ):
                self.close()
                raise ValueError(
                    "Validation checkpoint does not match the requested rules/scope"
                )
            if not self.recent(self.metadata.get("as_of")):
                self.close()
                raise ValueError(
                    "Validation checkpoint is older than seven days; start a fresh run"
                )
        else:
            as_of = request.get("evaluation_as_of")
            if as_of is not None and not self.recent(as_of):
                self.close()
                raise ValueError("Research cutoff must be within the last seven days")
            self.metadata = dict(
                version=self.VERSION,
                run_id=run_id,
                request=request,
                registry_version=registry_version,
                as_of=as_of or datetime.now(UTC).isoformat(),
            )
            self._save_meta()
        self.rows = {kind: JournalRows(self, kind) for kind in KINDS}

    def _save_meta(self):
        self.connection.execute(
            "INSERT OR REPLACE INTO meta VALUES(1,?)",
            (json.dumps(self.metadata, sort_keys=True, default=str),),
        )
        self.connection.commit()

    def bind_universe(self, symbols, membership_sets):
        identity = {
            "symbols": symbols,
            "memberships": {
                key: sorted(value) for key, value in membership_sets.items()
            },
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        if self.metadata.get("universe_hash") not in (None, digest):
            raise ValueError(
                "Universe membership changed; start a fresh validation run"
            )
        self.metadata["universe_hash"] = digest
        self._save_meta()

    def completed(self):
        return set(self.connection.execute("SELECT mode,symbol FROM units"))

    def retry_failed(self):
        """Requeue failed units atomically; retain successful units and the cutoff."""
        if any(rows.pending for rows in self.rows.values()):
            raise ValueError("Retry must begin before processing any new rows")
        with self.connection:
            cursor = self.connection.execute("DELETE FROM units WHERE errors_count>0")
        return cursor.rowcount

    def commit_unit(self, mode, symbol):
        arrays = [self.rows[k].pending for k in KINDS]
        payloads = [encode_rows(rows) for rows in arrays]
        with self.connection:
            self.connection.execute(
                "INSERT INTO units VALUES(?,?,?,?,?,?,?,?)",
                (mode, symbol, *payloads, *(len(rows) for rows in arrays)),
            )
        for rows in arrays:
            rows.clear()

    def close(self):
        self.connection.close()


def write_result(path, result, *, compressed=False):
    """Stream arrays and JSON encoding; never make a second full-result string."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    try:
        opener = gzip.open if compressed else open
        with opener(temporary, "wt", encoding="utf-8") as output:
            os.chmod(temporary, 0o600)
            output.write("{")
            for offset, (key, value) in enumerate(result.items()):
                if offset:
                    output.write(",")
                output.write(json.dumps(key) + ":")
                if isinstance(value, JournalRows):
                    output.write("[")
                    for index, row in enumerate(value):
                        if index:
                            output.write(",")
                        json.dump(
                            row,
                            output,
                            ensure_ascii=False,
                            separators=(",", ":"),
                            default=str,
                            allow_nan=False,
                        )
                    output.write("]")
                else:
                    json.dump(
                        value,
                        output,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                        allow_nan=False,
                    )
            output.write("}")
            output.flush()
            os.fsync(output.fileno())
        with temporary.open("r+b") as saved:
            os.fsync(saved.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def export_headers(path):
    with Path(path).open("rb") as source:
        return {"Content-Encoding": "gzip"} if source.read(2) == b"\x1f\x8b" else {}
