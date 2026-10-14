"""SQLite repository for bounded one-time scan continuation tokens."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable


class ContinuationNotFoundError(LookupError):
    pass


class ContinuationUnavailableError(RuntimeError):
    pass


class ContinuationExpiredError(RuntimeError):
    pass


class ContinuationAttemptLimitError(RuntimeError):
    pass


class DuplicateContinuationError(ValueError):
    pass


class ScanContinuationRepository:
    def __init__(
        self,
        db,
        *,
        now_provider: Callable[[], datetime] | None = None,
    ):
        self.db = db
        self._now_provider = now_provider or (
            lambda: datetime.now(timezone.utc)
        )

    def _now(self) -> datetime:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _timestamp(self) -> str:
        return self._now().isoformat()

    @staticmethod
    def _parse_timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _decode(cls, row):
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
        result["claim_attempts"] = int(
            result.get("claim_attempts") or 0
        )
        result["max_claim_attempts"] = int(
            result.get("max_claim_attempts") or 0
        )
        result["recovery_count"] = int(
            result.get("recovery_count") or 0
        )
        return result

    def _is_expired(
        self,
        record: dict[str, Any],
        *,
        now: datetime | None = None,
    ) -> bool:
        expires = self._parse_timestamp(record.get("expires_at"))
        if expires is None:
            return False
        return expires <= (now or self._now())

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
        ttl_seconds: int = 3600,
        max_claim_attempts: int = 3,
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

        ttl = max(60, int(ttl_seconds))
        attempts = max(1, int(max_claim_attempts))
        now_dt = self._now()
        now = now_dt.isoformat()
        expires_at = (
            now_dt + timedelta(seconds=ttl)
        ).isoformat()

        try:
            self.db.execute(
                """
                INSERT INTO scan_continuations(
                    token, parent_run_id, lineage_root_run_id,
                    generation, status, symbols_json, request_json,
                    child_run_id, created_at, claimed_at,
                    consumed_at, updated_at, expires_at,
                    claim_attempts, max_claim_attempts,
                    recovery_count, last_recovered_at
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    expires_at,
                    0,
                    attempts,
                    0,
                    None,
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

    def inspect_available(self, token: str) -> dict[str, Any]:
        record = self.by_token(token)
        if record is None:
            raise ContinuationNotFoundError(
                "scan continuation token not found"
            )
        if self._is_expired(record):
            raise ContinuationExpiredError(
                "scan continuation token has expired"
            )
        if (
            record.get("status") == "pending"
            and record.get("claim_attempts", 0)
            >= record.get("max_claim_attempts", 0)
        ):
            raise ContinuationAttemptLimitError(
                "scan continuation claim limit exhausted"
            )
        return record

    def claim(self, token: str, child_run_id: str) -> dict[str, Any]:
        token = str(token or "").strip()
        child_run_id = str(child_run_id or "").strip()

        current = self.inspect_available(token)
        if current.get("status") != "pending":
            raise ContinuationUnavailableError(
                "scan continuation token is not pending"
            )

        now_dt = self._now()
        now = now_dt.isoformat()
        cursor = self.db.execute(
            """
            UPDATE scan_continuations
            SET status='active',
                child_run_id=?,
                claimed_at=?,
                claim_attempts=claim_attempts + 1,
                updated_at=?
            WHERE token=?
              AND status='pending'
              AND claim_attempts < max_claim_attempts
              AND (expires_at IS NULL OR expires_at>?)
            """,
            (child_run_id, now, now, token, now),
        )
        if cursor.rowcount != 1:
            latest = self.by_token(token)
            if latest is None:
                raise ContinuationNotFoundError(
                    "scan continuation token not found"
                )
            if self._is_expired(latest, now=now_dt):
                raise ContinuationExpiredError(
                    "scan continuation token has expired"
                )
            if (
                latest.get("claim_attempts", 0)
                >= latest.get("max_claim_attempts", 0)
            ):
                raise ContinuationAttemptLimitError(
                    "scan continuation claim limit exhausted"
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

    def release(
        self,
        token: str,
        child_run_id: str,
    ) -> dict[str, Any] | None:
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

    def restore_pending(
        self,
        token: str,
        child_run_id: str,
    ) -> dict[str, Any] | None:
        """Roll back a child claim without resetting its attempt counter."""
        token = str(token or "").strip()
        child_run_id = str(child_run_id or "").strip()
        now = self._timestamp()
        self.db.execute(
            """
            UPDATE scan_continuations
            SET status='pending',
                child_run_id=NULL,
                claimed_at=NULL,
                consumed_at=NULL,
                updated_at=?
            WHERE token=?
              AND child_run_id=?
              AND status IN ('active','consumed')
            """,
            (now, token, child_run_id),
        )
        return self.by_token(token)

    def recover_stale_active(
        self,
        *,
        stale_after_seconds: int,
    ) -> int:
        now_dt = self._now()
        cutoff = (
            now_dt - timedelta(
                seconds=max(60, int(stale_after_seconds))
            )
        ).isoformat()
        now = now_dt.isoformat()
        cursor = self.db.execute(
            """
            UPDATE scan_continuations
            SET status='pending',
                child_run_id=NULL,
                claimed_at=NULL,
                updated_at=?,
                recovery_count=recovery_count + 1,
                last_recovered_at=?
            WHERE status='active'
              AND claimed_at IS NOT NULL
              AND claimed_at<=?
              AND (expires_at IS NULL OR expires_at>?)
            """,
            (now, now, cutoff, now),
        )
        return max(0, int(cursor.rowcount or 0))

    def cleanup_expired(
        self,
        *,
        retention_seconds: int,
        stale_active_seconds: int,
    ) -> int:
        now_dt = self._now()
        expiry_cutoff = (
            now_dt - timedelta(
                seconds=max(0, int(retention_seconds))
            )
        ).isoformat()
        stale_cutoff = (
            now_dt - timedelta(
                seconds=max(60, int(stale_active_seconds))
            )
        ).isoformat()
        cursor = self.db.execute(
            """
            DELETE FROM scan_continuations
            WHERE expires_at IS NOT NULL
              AND expires_at<=?
              AND (
                    status IN ('pending','consumed')
                    OR (
                        status='active'
                        AND claimed_at IS NOT NULL
                        AND claimed_at<=?
                    )
                  )
            """,
            (expiry_cutoff, stale_cutoff),
        )
        return max(0, int(cursor.rowcount or 0))

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

    def health(
        self,
        *,
        stale_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        try:
            rows = self.db.fetchall(
                """
                SELECT status, COUNT(*) AS total
                FROM scan_continuations
                GROUP BY status
                """
            )
            now = self._timestamp()
            expired_row = self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM scan_continuations
                WHERE expires_at IS NOT NULL
                  AND expires_at<=?
                """,
                (now,),
            )
            exhausted_row = self.db.fetchone(
                """
                SELECT COUNT(*) AS total
                FROM scan_continuations
                WHERE status='pending'
                  AND claim_attempts>=max_claim_attempts
                """
            )
            stale_active = 0
            if stale_after_seconds is not None:
                cutoff = (
                    self._now()
                    - timedelta(
                        seconds=max(
                            60,
                            int(stale_after_seconds),
                        )
                    )
                ).isoformat()
                stale_row = self.db.fetchone(
                    """
                    SELECT COUNT(*) AS total
                    FROM scan_continuations
                    WHERE status='active'
                      AND claimed_at IS NOT NULL
                      AND claimed_at<=?
                    """,
                    (cutoff,),
                )
                stale_active = int(
                    stale_row["total"]
                    if stale_row is not None
                    else 0
                )
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc).lower():
                return {
                    "status": "not_initialized",
                    "storage": "sqlite",
                    "pending": 0,
                    "active": 0,
                    "consumed": 0,
                    "records": 0,
                    "expired_records": 0,
                    "exhausted_pending": 0,
                    "stale_active": 0,
                    "reason": "schema_not_initialized",
                }
            return {
                "status": "degraded",
                "storage": "sqlite",
                "records": 0,
                "reason": "sqlite_operational_error",
                "error": str(exc),
            }

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
            "expired_records": int(
                expired_row["total"]
                if expired_row is not None
                else 0
            ),
            "exhausted_pending": int(
                exhausted_row["total"]
                if exhausted_row is not None
                else 0
            ),
            "stale_active": stale_active,
        }


__all__ = [
    "ContinuationAttemptLimitError",
    "ContinuationExpiredError",
    "ContinuationNotFoundError",
    "ContinuationUnavailableError",
    "DuplicateContinuationError",
    "ScanContinuationRepository",
]
