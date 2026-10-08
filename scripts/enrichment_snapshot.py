"""Export and verify read-only TrendForge enrichment snapshot bundles."""

from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Mapping

from providers import NSECorporateActionProvider
from providers.enrichment_adapters import (
    CorporateActionEnrichmentProvider,
    YahooInstitutionalEnrichmentProvider,
    YahooSectorEnrichmentProvider,
)
from providers.enrichment_snapshot_provider import (
    SCHEMA_VERSION,
    SNAPSHOT_FIELDS,
)


def _normalize_symbols(raw: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for token in str(raw or "").replace(";", ",").split(","):
        symbol = token.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        symbols.append(symbol)
    if not symbols:
        raise ValueError("At least one symbol is required")
    return symbols


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass

    if isinstance(value, float) and not math.isfinite(value):
        return None

    return str(value)


def _canonical_bytes(bundle: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            bundle,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            default=_json_default,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def export_snapshot(
    output: str | Path,
    *,
    symbols: list[str],
    pause_seconds: float = 1.5,
) -> dict[str, Any]:
    providers = {
        "corporate_actions": CorporateActionEnrichmentProvider(
            NSECorporateActionProvider(),
        ),
        "big_shark": YahooInstitutionalEnrichmentProvider(),
        "sector": YahooSectorEnrichmentProvider(),
    }

    records: dict[str, dict[str, Any]] = {}
    failures: dict[str, dict[str, str]] = {}

    for symbol in symbols:
        symbol_payload: dict[str, Any] = {}
        symbol_failures: dict[str, str] = {}

        for field in SNAPSHOT_FIELDS:
            provider = providers[field]
            try:
                value = provider.get(symbol)
                if value is not None:
                    symbol_payload[field] = value
            except Exception as exc:
                symbol_failures[field] = str(exc)

            if pause_seconds > 0:
                time.sleep(float(pause_seconds))

        records[symbol] = symbol_payload
        if symbol_failures:
            failures[symbol] = symbol_failures

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "symbols_requested": list(symbols),
        "symbols": records,
        "failures": failures,
        "provider_health": {
            field: provider.health()
            for field, provider in providers.items()
        },
    }

    payload = _canonical_bytes(bundle)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    digest = _sha256(payload)

    coverage = {
        field: sum(
            1
            for record in records.values()
            if field in record
        )
        for field in SNAPSHOT_FIELDS
    }

    return {
        "status": "exported",
        "file": str(path.resolve()),
        "file_sha256": digest,
        "size_bytes": len(payload),
        "symbols_requested": len(symbols),
        "symbols_written": len(records),
        "coverage": coverage,
        "failure_symbols": len(failures),
        "failures": failures,
    }


def verify_snapshot(
    source: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    path = Path(source)
    raw = path.read_bytes()
    digest = _sha256(raw)

    expected = str(expected_sha256 or "").strip().lower()
    if expected and digest != expected:
        raise ValueError(
            "Enrichment snapshot SHA256 mismatch: "
            f"expected {expected}, got {digest}"
        )

    bundle = json.loads(raw.decode("utf-8"))
    if not isinstance(bundle, Mapping):
        raise ValueError("Snapshot root must be a JSON object")
    if int(bundle.get("schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError("Unsupported enrichment snapshot schema version")

    symbols = bundle.get("symbols")
    if not isinstance(symbols, Mapping):
        raise ValueError("Snapshot must contain a symbols object")

    coverage = {
        field: sum(
            1
            for record in symbols.values()
            if isinstance(record, Mapping) and field in record
        )
        for field in SNAPSHOT_FIELDS
    }

    return {
        "status": "verified",
        "file": str(path.resolve()),
        "file_sha256": digest,
        "pinned_sha256": bool(expected),
        "size_bytes": len(raw),
        "symbols": len(symbols),
        "coverage": coverage,
        "failure_symbols": len(bundle.get("failures") or {}),
        "generated_at": bundle.get("generated_at"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a scanner enrichment snapshot outside the Render "
            "request path, then use it as a read-only production source."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export")
    export.add_argument("--out", required=True)
    export.add_argument(
        "--symbols",
        required=True,
        help="Comma-separated NSE symbols",
    )
    export.add_argument(
        "--pause",
        type=float,
        default=1.5,
        help="Pause between upstream calls in seconds",
    )

    verify = sub.add_parser("verify")
    verify.add_argument("file")
    verify.add_argument("--sha256", default=None)

    args = parser.parse_args()

    if args.command == "export":
        result = export_snapshot(
            args.out,
            symbols=_normalize_symbols(args.symbols),
            pause_seconds=max(0.0, float(args.pause)),
        )
    else:
        result = verify_snapshot(
            args.file,
            expected_sha256=args.sha256,
        )

    print(json.dumps(result, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
