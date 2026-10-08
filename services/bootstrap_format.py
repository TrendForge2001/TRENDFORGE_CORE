"""Format and integrity helpers for fundamental bootstrap bundles."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
from typing import Any

SCHEMA_VERSION = 1
MAX_BYTES = 1024 * 1024


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def body_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        key: bundle[key]
        for key in (
            "schema_version",
            "generated_at",
            "fundamentals",
            "evidence",
            "field_updates",
        )
    }


def validate_bundle(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise ValueError("Bootstrap root must be a JSON object")
    if bundle.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported bootstrap schema version")
    for key in ("fundamentals", "evidence", "field_updates"):
        if not isinstance(bundle.get(key), list):
            raise ValueError(f"Bootstrap field {key!r} must be a list")
    if not bundle["fundamentals"]:
        raise ValueError("Bootstrap must contain fundamentals")
    digest = str(bundle.get("payload_sha256") or "").strip().lower()
    if len(digest) != 64:
        raise ValueError("Bootstrap payload_sha256 is invalid")
    actual = sha256_bytes(canonical_bytes(body_from_bundle(bundle)))
    if not secrets.compare_digest(actual, digest):
        raise ValueError("Bootstrap payload SHA256 validation failed")
    return bundle


def read_verified_bundle(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
    require_pinned_sha256: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source = Path(path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"Bootstrap file not found: {source}")
    raw = source.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Bootstrap exceeds the 1 MB safety limit")
    file_digest = sha256_bytes(raw)
    pinned = str(expected_file_sha256 or "").strip().lower()
    if require_pinned_sha256 and not pinned:
        raise ValueError("Pinned bootstrap SHA256 is required")
    if pinned and not secrets.compare_digest(file_digest, pinned):
        raise ValueError("Bootstrap file SHA256 does not match")
    try:
        bundle = validate_bundle(json.loads(raw.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Bootstrap is not valid UTF-8 JSON") from exc
    return bundle, {
        "file": str(source),
        "file_sha256": file_digest,
        "payload_sha256": bundle["payload_sha256"],
        "size_bytes": len(raw),
        "pinned_sha256_verified": bool(pinned),
    }


def encode_bundle(body: dict[str, Any]) -> bytes:
    bundle = dict(body)
    bundle["payload_sha256"] = sha256_bytes(canonical_bytes(body))
    raw = (json.dumps(bundle, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    if len(raw) > MAX_BYTES:
        raise ValueError("Bootstrap exceeds the 1 MB Render secret-file limit")
    return raw
