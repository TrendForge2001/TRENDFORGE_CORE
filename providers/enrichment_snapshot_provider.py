"""Read-only enrichment snapshot provider for production-safe scanner inputs."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
SNAPSHOT_FIELDS = (
    "corporate_actions",
    "big_shark",
    "sector",
)

BIG_SHARK_EVIDENCE_FIELDS = (
    "shareholding",
    "shareholding_snapshot",
    "shareholders",
    "institutional_holders",
    "institutional_activity",
    "holding_changes",
    "fii",
    "dii",
    "mutual_fund",
    "mutual_funds",
    "insurance",
    "promoter",
    "deals",
    "block_deals",
    "bulk_deals",
)


def has_big_shark_evidence(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False

    for field in BIG_SHARK_EVIDENCE_FIELDS:
        item = value.get(field)
        if item in (None, "", [], {}):
            continue

        if isinstance(item, Mapping):
            meaningful = {
                key: nested
                for key, nested in item.items()
                if not str(key).startswith("_")
                and nested not in (None, "", [], {})
            }
            if meaningful:
                return True
            continue

        return True

    return False


def field_has_evidence(field: str, value: Any) -> bool:
    if field == "big_shark":
        return has_big_shark_evidence(value)
    # An empty corporate-action list is meaningful evidence: the upstream
    # source was queried successfully and found no matching event.
    return value is not None


class EnrichmentSnapshotError(RuntimeError):
    """Raised when a configured enrichment snapshot is invalid."""


class EnrichmentSnapshot:
    """Load and verify one immutable enrichment snapshot bundle."""

    def __init__(
        self,
        path: str | Path,
        *,
        expected_sha256: str | None = None,
    ) -> None:
        self.path = Path(path)
        self.expected_sha256 = (
            str(expected_sha256 or "").strip().lower() or None
        )
        self._bundle: dict[str, Any] = {}
        self._file_sha256 = ""
        self._load()

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _load(self) -> None:
        if not self.path.is_file():
            raise EnrichmentSnapshotError(
                f"Enrichment snapshot not found: {self.path}"
            )

        raw = self.path.read_bytes()
        digest = self._sha256(raw)

        if (
            self.expected_sha256 is not None
            and digest != self.expected_sha256
        ):
            raise EnrichmentSnapshotError(
                "Enrichment snapshot SHA256 mismatch: "
                f"expected {self.expected_sha256}, got {digest}"
            )

        try:
            bundle = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnrichmentSnapshotError(
                f"Enrichment snapshot is not valid UTF-8 JSON: {exc}"
            ) from exc

        if not isinstance(bundle, Mapping):
            raise EnrichmentSnapshotError(
                "Enrichment snapshot root must be a JSON object"
            )

        if int(bundle.get("schema_version") or 0) != SCHEMA_VERSION:
            raise EnrichmentSnapshotError(
                "Unsupported enrichment snapshot schema version"
            )

        symbols = bundle.get("symbols")
        if not isinstance(symbols, Mapping):
            raise EnrichmentSnapshotError(
                "Enrichment snapshot must contain a symbols object"
            )

        normalized: dict[str, dict[str, Any]] = {}
        for raw_symbol, raw_payload in symbols.items():
            symbol = str(raw_symbol or "").strip().upper()
            if not symbol or not isinstance(raw_payload, Mapping):
                continue

            payload: dict[str, Any] = {}
            for field in SNAPSHOT_FIELDS:
                if field in raw_payload:
                    payload[field] = deepcopy(raw_payload[field])
            normalized[symbol] = payload

        self._bundle = {
            **dict(bundle),
            "symbols": normalized,
        }
        self._file_sha256 = digest

    @property
    def file_sha256(self) -> str:
        return self._file_sha256

    @property
    def generated_at(self) -> str | None:
        value = self._bundle.get("generated_at")
        return str(value) if value else None

    def get(
        self,
        field: str,
        symbol: str,
    ) -> Any:
        if field not in SNAPSHOT_FIELDS:
            raise ValueError(
                f"Unsupported snapshot enrichment field: {field}"
            )

        symbol = str(symbol or "").strip().upper()
        payload = self._bundle["symbols"].get(symbol)
        if not isinstance(payload, Mapping):
            return None

        if field not in payload:
            return None

        return deepcopy(payload[field])

    def field_count(self, field: str) -> int:
        return sum(
            1
            for payload in self._bundle["symbols"].values()
            if isinstance(payload, Mapping) and field in payload
        )

    def evidence_count(self, field: str) -> int:
        return sum(
            1
            for payload in self._bundle["symbols"].values()
            if isinstance(payload, Mapping)
            and field in payload
            and field_has_evidence(field, payload[field])
        )

    def symbol_count(self) -> int:
        return len(self._bundle["symbols"])

    def health(self) -> dict[str, Any]:
        counts = {
            field: self.field_count(field)
            for field in SNAPSHOT_FIELDS
        }
        evidence_counts = {
            field: self.evidence_count(field)
            for field in SNAPSHOT_FIELDS
        }
        return {
            "status": "runtime_verified",
            "provider": self.__class__.__name__,
            "source": str(self.path),
            "schema_version": SCHEMA_VERSION,
            "generated_at": self.generated_at,
            "symbols_loaded": self.symbol_count(),
            "field_records": counts,
            "evidence_records": evidence_counts,
            "file_sha256": self.file_sha256,
            "pinned_sha256": self.expected_sha256 is not None,
            "network_probe": False,
        }


class SnapshotFieldProvider:
    """Expose one snapshot field through StockEnricher's provider contract."""

    def __init__(
        self,
        snapshot: EnrichmentSnapshot,
        field: str,
    ) -> None:
        if field not in SNAPSHOT_FIELDS:
            raise ValueError(
                f"Unsupported snapshot enrichment field: {field}"
            )
        self.snapshot = snapshot
        self.field = field

    def get(
        self,
        symbol: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        return self.snapshot.get(self.field, symbol)

    def health(self) -> dict[str, Any]:
        base = self.snapshot.health()
        return {
            **base,
            "provider": self.__class__.__name__,
            "field": self.field,
            "field_records": self.snapshot.field_count(self.field),
            "evidence_records": self.snapshot.evidence_count(self.field),
        }


__all__ = [
    "SCHEMA_VERSION",
    "SNAPSHOT_FIELDS",
    "BIG_SHARK_EVIDENCE_FIELDS",
    "field_has_evidence",
    "has_big_shark_evidence",
    "EnrichmentSnapshot",
    "EnrichmentSnapshotError",
    "SnapshotFieldProvider",
]
