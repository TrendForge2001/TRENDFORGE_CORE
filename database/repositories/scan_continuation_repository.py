"""SQLite repository for one-time scan continuation tokens."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any


class ContinuationNotFoundError(LookupError):
    pass


class ContinuationUnavailableError(RuntimeError):
    pass


class DuplicateContinuationError(ValueError):
    pass


class ScanContinuationRepository:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for source, target, default in (
            ("symbols_json", "symbols", []),
            ("request_json", "request", {}),
        ):
            raw = result.pop(source, None)
            try:
                result[target] = json.loads(raw) if raw else default
            except (TypeError, ValueError):
                result[target] = default
        result["generation"] = int(result.get("generation") or 1)
        return result

    def by_token(self, token: str) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM scan_continuations WHERE token=?",
            (str(token or "").strip(),),
        )
        return self._decode(row)

    def by_parent_run_id(
        self,
        parent_run_id: str,
    ) -> dict[str, Any] | None:
        row = self.db.fetchone(
            "SELECT * FROM scan_continuations WHERE parent_run_id=?",
            (str(parent_run_id or "").strip(),),
        )
        return self._decode(row)

    def create(
        self,
        *,
        token: str,
        parent_run_id: str,
        lineage_root_run_id: str,
        generation: int,
        symbols: list[str],
        request: dict[str, Any],
    ) -> dict[str, Any]:
        token = str(token or "").strip()
        parent_run_id = str(parent_run_id or "").strip()
        lineage_root_run_id = str(lineage_root_run_id or "").strip()
        normalized = []
        seen = set()
        for raw in symbols or []:
            symbol = str(raw or "").strip().upper()
            if symbol and symbol not in seen:
                normalized.append(symbol)
                seen.add(symbol)

        if not token or not parent_run_id or not lineage_root_run_id:
            raise ValueError(
                "continuation token, parent_run_id and lineage root are required"
            )
        if not normalized:
            raise ValueError(
                "continuation requires at least one deferred symbol"
            )

        now = self._timestamp()
        try:
            self.db.execute(
                """
                INSERT INTO scan_continuations(
                    token, parent_run_id, lineage_root_run_id,
                    generation, status, symbols_json, request_json,
                    child_run_id, created_at, claimed_at,
                    consumed_at, updated_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    token,
                    parent_run_id,
                    lineage_root_run_id,
                    max(1, int(generation)),
                    "pending",
                    json.dumps(normalized),
                    json.dumps(request or {}, sort_keys=True),
                    None,
                    now,
                    None,
                    None,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.by_parent_run_id(parent_run_id)
            if existing is not None:
                raise DuplicateContinuationError(
                    f"continuation already exists for parent run {parent_run_id}"
                ) from exc
            raise

        result = self.by_token(token)
        if result is None:
            raise RuntimeError("continuation token could not be persisted")
        return result

    def claim(self, token: str, child_run_id: str) -> dict[str, Any]:
        token = str(token or "").strip()
        child_run_id = str(child_run_id or "").strip()
        now = self._timestamp()
        cursor = self.db.execute(
            """
            UPDATE scan_continuations
            SET status='active',
                child_run_id=?,
                claimed_at=?,
                updated_at=?
            WHERE token=? AND status='pending'
            """,
            (child_run_id, now, now, token),
        )
        if cursor.rowcount != 1:
            current = self.by_token(token)
            if current is None:
                raise ContinuationNotFoundError(
                    "scan continuation token not found"
                )
            raise ContinuationUnavailableError(
                "scan continuation token is not pending"
            )

        result = self.by_token(token)
        if result is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        return result

    def release(self, token: str, child_run_id: str) -> dict[str, Any] | None:
        token = str(token or "").strip()
        child_run_id = str(child_run_id or "").strip()
        now = self._timestamp()
        self.db.execute(
            """
            UPDATE scan_continuations
            SET status='pending',
                child_run_id=NULL,
                claimed_at=NULL,
                updated_at=?
            WHERE token=?
              AND status='active'
              AND child_run_id=?
            """,
            (now, token, child_run_id),
        )
        return self.by_token(token)

    def consume(self, token: str, child_run_id: str) -> dict[str, Any]:
        token = str(token or "").strip()
        child_run_id = str(child_run_id or "").strip()
        now = self._timestamp()
        cursor = self.db.execute(
            """
            UPDATE scan_continuations
            SET status='consumed',
                consumed_at=?,
                updated_at=?
            WHERE token=?
              AND status='active'
              AND child_run_id=?
            """,
            (now, now, token, child_run_id),
        )
        if cursor.rowcount != 1:
            current = self.by_token(token)
            if current is None:
                raise ContinuationNotFoundError(
                    "scan continuation token not found"
                )
            raise ContinuationUnavailableError(
                "scan continuation token could not be consumed"
            )

        result = self.by_token(token)
        if result is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        return result

    def delete_pending(self, token: str, parent_run_id: str) -> None:
        self.db.execute(
            """
            DELETE FROM scan_continuations
            WHERE token=?
              AND parent_run_id=?
              AND status='pending'
              AND child_run_id IS NULL
            """,
            (
                str(token or "").strip(),
                str(parent_run_id or "").strip(),
            ),
        )

    def health(self) -> dict[str, Any]:
        rows = self.db.fetchall(
            """
            SELECT status, COUNT(*) AS total
            FROM scan_continuations
            GROUP BY status
            """
        )
        counts = {
            str(row["status"]): int(row["total"])
            for row in rows
        }
        return {
            "status": "ready",
            "storage": "sqlite",
            "pending": counts.get("pending", 0),
            "active": counts.get("active", 0),
            "consumed": counts.get("consumed", 0),
            "records": sum(counts.values()),
        }


__all__ = [
    "ContinuationNotFoundError",
    "ContinuationUnavailableError",
    "DuplicateContinuationError",
    "ScanContinuationRepository",
]
