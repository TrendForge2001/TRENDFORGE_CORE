"""Export and empty-only restore of canonical fundamental data."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from database.repositories.fundamental_field_evidence_repository import (
    FundamentalFieldEvidenceRepository,
)
from database.repositories.fundamental_field_update_repository import (
    FundamentalFieldUpdateRepository,
)
from database.repositories.fundamentals_repository import FundamentalsRepository
from services.bootstrap_format import (
    SCHEMA_VERSION,
    encode_bundle,
    read_verified_bundle,
    sha256_bytes,
)


class FundamentalBootstrapService:
    def __init__(self, *, db_path: str | None = None) -> None:
        self.fundamentals = FundamentalsRepository(db_path=db_path)
        db = self.fundamentals.db
        self.evidence = FundamentalFieldEvidenceRepository(db=db)
        self.updates = FundamentalFieldUpdateRepository(db=db)

    def _all_evidence(self) -> list[dict[str, Any]]:
        columns = ", ".join(FundamentalFieldEvidenceRepository.FIELDS)
        rows = self.fundamentals.db.fetchall(
            f"SELECT {columns} FROM fundamental_field_evidence ORDER BY id"
        )
        return [dict(row) for row in rows]

    def _all_updates(self) -> list[dict[str, Any]]:
        rows = self.fundamentals.db.fetchall(
            """
            SELECT symbol, field, value, source, source_file, as_of, imported_at
            FROM fundamental_field_updates
            ORDER BY id
            """
        )
        return [dict(row) for row in rows]

    def export_bundle(self, path: str | Path) -> dict[str, Any]:
        body = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fundamentals": self.fundamentals.all(limit=10000),
            "evidence": self._all_evidence(),
            "field_updates": self._all_updates(),
        }
        raw = encode_bundle(body)
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return {
            "status": "exported",
            "file": str(target),
            "fundamental_records": len(body["fundamentals"]),
            "evidence_records": len(body["evidence"]),
            "field_update_records": len(body["field_updates"]),
            "file_sha256": sha256_bytes(raw),
            "size_bytes": len(raw),
        }

    @staticmethod
    def _validate_rows(bundle: dict[str, Any]) -> None:
        for index, row in enumerate(bundle["fundamentals"], start=1):
            if not isinstance(row, dict) or not FundamentalsRepository.normalize_symbol(
                row.get("symbol")
            ):
                raise ValueError(f"Invalid fundamental bootstrap row {index}")
        required = (
            "symbol", "field", "value_status", "source_type",
            "source", "source_ref", "as_of",
        )
        for index, row in enumerate(bundle["evidence"], start=1):
            if not isinstance(row, dict):
                raise ValueError(f"Invalid evidence bootstrap row {index}")
            missing = [key for key in required if not str(row.get(key) or "").strip()]
            if missing:
                raise ValueError(
                    f"Evidence bootstrap row {index} is missing: "
                    + ", ".join(missing)
                )

    def verify_bundle(
        self,
        path: str | Path,
        *,
        expected_file_sha256: str | None = None,
        require_pinned_sha256: bool = True,
    ) -> dict[str, Any]:
        bundle, meta = read_verified_bundle(
            path,
            expected_file_sha256=expected_file_sha256,
            require_pinned_sha256=require_pinned_sha256,
        )
        self._validate_rows(bundle)
        return {
            "status": "verified",
            **meta,
            "fundamental_records": len(bundle["fundamentals"]),
            "evidence_records": len(bundle["evidence"]),
            "field_update_records": len(bundle["field_updates"]),
        }

    def apply_bundle(
        self,
        path: str | Path,
        *,
        expected_file_sha256: str | None = None,
        require_pinned_sha256: bool = True,
    ) -> dict[str, Any]:
        existing = self.fundamentals.count()
        if existing:
            return {
                "status": "skipped_nonempty",
                "database_records": existing,
                "reason": "Startup bootstrap never overwrites existing fundamentals.",
            }
        bundle, meta = read_verified_bundle(
            path,
            expected_file_sha256=expected_file_sha256,
            require_pinned_sha256=require_pinned_sha256,
        )
        self._validate_rows(bundle)
        try:
            fundamentals = self.fundamentals.save_many(bundle["fundamentals"])
            evidence = self.evidence.add_many(bundle["evidence"])
            updates = self.updates.add_many(bundle["field_updates"])
            if evidence != len(bundle["evidence"]):
                raise ValueError("Not all evidence rows were accepted")
            if updates != len(bundle["field_updates"]):
                raise ValueError("Not all field-update rows were accepted")
        except Exception:
            self.fundamentals.db.execute("DELETE FROM fundamental_field_evidence")
            self.fundamentals.db.execute("DELETE FROM fundamental_field_updates")
            self.fundamentals.clear()
            raise
        return {
            "status": "applied",
            **meta,
            "fundamental_records": fundamentals,
            "evidence_records": evidence,
            "field_update_records": updates,
            "database_records": self.fundamentals.count(),
        }

    def close(self) -> None:
        self.fundamentals.close()


__all__ = ["FundamentalBootstrapService"]
