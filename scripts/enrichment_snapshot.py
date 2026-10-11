"""Export, expand and verify read-only TrendForge enrichment snapshots."""

from __future__ import annotations

import argparse
from copy import deepcopy
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
    field_has_evidence,
    field_has_signal_evidence,
)
from providers.nse_index_constituents import (
    NSEIndexConstituentProvider,
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
            return _sanitize_json(item())
        except Exception:
            pass

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass

    return str(value)


def _sanitize_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_json(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _sanitize_json(item())
        except Exception:
            pass

    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:
            pass

    return value


def _canonical_bytes(bundle: Mapping[str, Any]) -> bytes:
    safe_bundle = _sanitize_json(bundle)
    return (
        json.dumps(
            safe_bundle,
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


def _snapshot_metrics(
    records: Mapping[str, Any],
) -> tuple[
    dict[str, int],
    dict[str, int],
    dict[str, int],
]:
    field_records = {
        field: sum(
            1
            for record in records.values()
            if isinstance(record, Mapping)
            and field in record
        )
        for field in SNAPSHOT_FIELDS
    }
    coverage = {
        field: sum(
            1
            for record in records.values()
            if isinstance(record, Mapping)
            and field in record
            and field_has_evidence(field, record[field])
        )
        for field in SNAPSHOT_FIELDS
    }
    signal_coverage = {
        field: sum(
            1
            for record in records.values()
            if isinstance(record, Mapping)
            and field in record
            and field_has_signal_evidence(
                field,
                record[field],
            )
        )
        for field in SNAPSHOT_FIELDS
    }
    return field_records, coverage, signal_coverage


def _write_bundle(
    output: str | Path,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _canonical_bytes(bundle)
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "file": str(path.resolve()),
        "file_sha256": _sha256(payload),
        "size_bytes": len(payload),
    }


def _read_bundle(source: str | Path) -> dict[str, Any]:
    path = Path(source)
    raw = path.read_bytes()
    bundle = json.loads(raw.decode("utf-8"))
    if not isinstance(bundle, Mapping):
        raise ValueError("Snapshot root must be a JSON object")
    if int(bundle.get("schema_version") or 0) != SCHEMA_VERSION:
        raise ValueError("Unsupported enrichment snapshot schema version")
    symbols = bundle.get("symbols")
    if not isinstance(symbols, Mapping):
        raise ValueError("Snapshot must contain a symbols object")
    return dict(bundle)


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

    file_info = _write_bundle(output, bundle)
    field_records, coverage, signal_coverage = _snapshot_metrics(
        records
    )

    return {
        "status": "exported",
        **file_info,
        "symbols_requested": len(symbols),
        "symbols_written": len(records),
        "field_records": field_records,
        "coverage": coverage,
        "signal_coverage": signal_coverage,
        "failure_symbols": len(failures),
        "failures": failures,
    }


def _base_records(
    base_snapshot: str | Path | None,
    *,
    allowed_symbols: set[str],
) -> dict[str, dict[str, Any]]:
    if base_snapshot is None:
        return {
            symbol: {}
            for symbol in sorted(allowed_symbols)
        }

    bundle = _read_bundle(base_snapshot)
    raw_symbols = bundle.get("symbols") or {}
    records: dict[str, dict[str, Any]] = {}

    for symbol in sorted(allowed_symbols):
        raw = raw_symbols.get(symbol)
        payload: dict[str, Any] = {}
        if isinstance(raw, Mapping):
            for field in SNAPSHOT_FIELDS:
                if field in raw:
                    payload[field] = deepcopy(raw[field])
        records[symbol] = payload

    return records


def _classification_only_sector(
    *,
    symbol: str,
    classification: str,
    error: str | None = None,
) -> dict[str, Any]:
    source_errors = [error] if error else []
    return {
        "sector": classification,
        "industry": classification,
        "_meta": {
            "provider": "NSEIndexConstituentProvider",
            "metadata_source": "NSE_NIFTY500_CSV",
            "proxy_available": False,
            "signal_evidence": False,
            "classification_only": True,
            "source_errors": source_errors,
            "symbol": symbol,
        },
    }


def expand_nifty500_snapshot(
    output: str | Path,
    *,
    base_snapshot: str | Path | None = None,
    corporate_days: int = 120,
    include_big_shark: bool = False,
    pause_seconds: float = 0.25,
    universe_provider: Any | None = None,
    corporate_provider: Any | None = None,
    sector_provider: Any | None = None,
    big_shark_provider: Any | None = None,
) -> dict[str, Any]:
    """Expand a snapshot over the current official NIFTY 500 securities.

    Corporate actions use one broad successful upstream query, allowing a
    source-backed empty list to be recorded for symbols with no events.
    Sector classification comes from the official constituent CSV; proxy
    momentum is added when available without per-company metadata requests.
    """

    universe_provider = (
        universe_provider
        or NSEIndexConstituentProvider()
    )
    universe = universe_provider.nifty500(force_refresh=True)
    members = list(universe.get("members") or [])
    symbols = [
        str(member.get("symbol") or "").strip().upper()
        for member in members
        if isinstance(member, Mapping)
        and str(member.get("symbol") or "").strip()
    ]

    if (
        len(symbols) < 500
        or len(symbols) > 525
        or len(symbols) != len(set(symbols))
    ):
        raise RuntimeError(
            "NIFTY 500 universe failed snapshot expansion gate: "
            f"received {len(symbols)} unique/security rows"
        )

    allowed = set(symbols)
    records = _base_records(
        base_snapshot,
        allowed_symbols=allowed,
    )
    failures: dict[str, dict[str, str]] = {}
    global_failures: dict[str, str] = {}

    corporate_provider = (
        corporate_provider
        or CorporateActionEnrichmentProvider(
            NSECorporateActionProvider(),
        )
    )
    sector_provider = (
        sector_provider
        or YahooSectorEnrichmentProvider()
    )
    big_shark_provider = (
        big_shark_provider
        or YahooInstitutionalEnrichmentProvider()
    )

    get_many = getattr(corporate_provider, "get_many", None)
    if not callable(get_many):
        raise TypeError(
            "Corporate-action provider must expose get_many() "
            "for NIFTY 500 snapshot expansion"
        )

    try:
        corporate = get_many(
            symbols,
            days=max(1, int(corporate_days)),
        )
        if set(corporate) != allowed:
            missing = sorted(allowed - set(corporate))
            extra = sorted(set(corporate) - allowed)
            raise RuntimeError(
                "Corporate-action bulk result did not account for "
                f"the universe; missing={missing[:10]}, extra={extra[:10]}"
            )
        for symbol in symbols:
            records[symbol]["corporate_actions"] = list(
                corporate[symbol]
            )
    except Exception as exc:
        global_failures["corporate_actions"] = str(exc)

    members_by_symbol = {
        str(member.get("symbol") or "").strip().upper(): member
        for member in members
        if isinstance(member, Mapping)
    }

    get_from_classification = getattr(
        sector_provider,
        "get_from_classification",
        None,
    )
    if not callable(get_from_classification):
        raise TypeError(
            "Sector provider must expose get_from_classification() "
            "for NIFTY 500 snapshot expansion"
        )

    for symbol in symbols:
        member = members_by_symbol[symbol]
        classification = str(
            member.get("sector")
            or member.get("industry")
            or ""
        ).strip()

        if not classification:
            failures.setdefault(symbol, {})["sector"] = (
                "Official NIFTY 500 constituent row has no industry"
            )
            continue

        try:
            sector_value = get_from_classification(
                symbol,
                sector=classification,
                industry=classification,
                metadata_source="NSE_NIFTY500_CSV",
                allow_classification_only=True,
            )
        except Exception as exc:
            # The classification itself is still official source evidence.
            # Preserve it explicitly without inventing sector momentum.
            sector_value = _classification_only_sector(
                symbol=symbol,
                classification=classification,
                error=str(exc),
            )
            failures.setdefault(symbol, {})["sector_signal"] = str(exc)

        records[symbol]["sector"] = sector_value

    if include_big_shark:
        for symbol in symbols:
            try:
                value = big_shark_provider.get(symbol)
                if value is not None:
                    records[symbol]["big_shark"] = value
            except Exception as exc:
                failures.setdefault(symbol, {})["big_shark"] = str(exc)

            if pause_seconds > 0:
                time.sleep(float(pause_seconds))

    field_records, coverage, signal_coverage = _snapshot_metrics(
        records
    )

    security_count = len(symbols)
    production_fields_complete = (
        coverage["corporate_actions"] == security_count
        and coverage["sector"] == security_count
        and not global_failures
    )

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "symbols_requested": list(symbols),
        "symbols": records,
        "failures": failures,
        "global_failures": global_failures,
        "universe": {
            "index": universe.get("index") or "NIFTY 500",
            "source": universe.get("source"),
            "source_url": universe.get("source_url"),
            "nominal_company_count": universe.get(
                "nominal_company_count",
                500,
            ),
            "security_count": security_count,
            "count_variance": universe.get(
                "count_variance",
                security_count - 500,
            ),
            "fetched_at": universe.get("fetched_at"),
            "source_last_modified": universe.get(
                "source_last_modified"
            ),
            "source_etag": universe.get("source_etag"),
        },
        "expansion": {
            "mode": "NIFTY500",
            "base_snapshot": (
                str(Path(base_snapshot).resolve())
                if base_snapshot is not None
                else None
            ),
            "corporate_days": max(1, int(corporate_days)),
            "include_big_shark": bool(include_big_shark),
            "production_fields_complete":
                production_fields_complete,
        },
        "provider_health": {
            "universe": (
                universe_provider.health()
                if callable(
                    getattr(universe_provider, "health", None)
                )
                else {"status": "unknown"}
            ),
            "corporate_actions": corporate_provider.health(),
            "sector": sector_provider.health(),
            "big_shark": big_shark_provider.health(),
        },
    }

    file_info = _write_bundle(output, bundle)

    return {
        "status": (
            "expanded"
            if production_fields_complete
            else "partial"
        ),
        **file_info,
        "universe_source": universe.get("source"),
        "nominal_company_count": universe.get(
            "nominal_company_count",
            500,
        ),
        "security_count": security_count,
        "field_records": field_records,
        "coverage": coverage,
        "signal_coverage": signal_coverage,
        "sector_classification_only": (
            coverage["sector"]
            - signal_coverage["sector"]
        ),
        "production_fields_complete":
            production_fields_complete,
        "failure_symbols": len(failures),
        "global_failures": global_failures,
        "include_big_shark": bool(include_big_shark),
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

    bundle = _read_bundle(path)
    symbols = bundle["symbols"]
    field_records, coverage, signal_coverage = _snapshot_metrics(
        symbols
    )

    return {
        "status": "verified",
        "file": str(path.resolve()),
        "file_sha256": digest,
        "pinned_sha256": bool(expected),
        "size_bytes": len(raw),
        "symbols": len(symbols),
        "field_records": field_records,
        "coverage": coverage,
        "signal_coverage": signal_coverage,
        "failure_symbols": len(bundle.get("failures") or {}),
        "global_failures": dict(
            bundle.get("global_failures") or {}
        ),
        "generated_at": bundle.get("generated_at"),
        "universe": bundle.get("universe"),
        "expansion": bundle.get("expansion"),
    }


def verify_nifty500_snapshot(
    source: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    result = verify_snapshot(
        source,
        expected_sha256=expected_sha256,
    )
    bundle = _read_bundle(source)
    universe = bundle.get("universe")
    if not isinstance(universe, Mapping):
        raise ValueError(
            "NIFTY 500 snapshot must include universe metadata"
        )

    if universe.get("source") != "NSE_NIFTY500_CSV":
        raise ValueError(
            "NIFTY 500 snapshot must use NSE_NIFTY500_CSV universe"
        )

    security_count = int(
        universe.get("security_count")
        or result["symbols"]
    )
    if not 500 <= security_count <= 525:
        raise ValueError(
            "NIFTY 500 snapshot security count outside validated bounds"
        )
    if result["symbols"] != security_count:
        raise ValueError(
            "NIFTY 500 snapshot symbol count does not match universe "
            f"metadata: {result['symbols']} != {security_count}"
        )

    corporate_complete = (
        result["coverage"]["corporate_actions"]
        == security_count
    )
    sector_complete = (
        result["coverage"]["sector"]
        == security_count
    )
    no_global_failures = not result["global_failures"]
    production_ready = (
        corporate_complete
        and sector_complete
        and no_global_failures
    )

    return {
        **result,
        "status": (
            "production_ready"
            if production_ready
            else "incomplete"
        ),
        "security_count": security_count,
        "corporate_actions_complete": corporate_complete,
        "sector_complete": sector_complete,
        "sector_signal_coverage": result[
            "signal_coverage"
        ]["sector"],
        "sector_classification_only": (
            result["coverage"]["sector"]
            - result["signal_coverage"]["sector"]
        ),
        "production_ready": production_ready,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build scanner enrichment snapshots outside the Render "
            "request path, then use them as read-only production sources."
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

    expand = sub.add_parser("expand-nifty500")
    expand.add_argument("--out", required=True)
    expand.add_argument(
        "--base",
        default=None,
        help=(
            "Optional prior snapshot. Existing Big Shark evidence is "
            "preserved for symbols still in the official universe."
        ),
    )
    expand.add_argument(
        "--corporate-days",
        type=int,
        default=120,
        help="Corporate-action lookback window",
    )
    expand.add_argument(
        "--include-big-shark",
        action="store_true",
        help=(
            "Also refresh Big Shark for the full universe. This is "
            "intentionally opt-in because it is a high-request-volume path."
        ),
    )
    expand.add_argument(
        "--pause",
        type=float,
        default=0.25,
        help="Pause between optional Big Shark symbol calls",
    )

    verify = sub.add_parser("verify")
    verify.add_argument("file")
    verify.add_argument("--sha256", default=None)

    verify_nifty = sub.add_parser("verify-nifty500")
    verify_nifty.add_argument("file")
    verify_nifty.add_argument("--sha256", default=None)

    args = parser.parse_args()

    if args.command == "export":
        result = export_snapshot(
            args.out,
            symbols=_normalize_symbols(args.symbols),
            pause_seconds=max(0.0, float(args.pause)),
        )
        exit_code = 0
    elif args.command == "expand-nifty500":
        result = expand_nifty500_snapshot(
            args.out,
            base_snapshot=args.base,
            corporate_days=max(1, int(args.corporate_days)),
            include_big_shark=bool(args.include_big_shark),
            pause_seconds=max(0.0, float(args.pause)),
        )
        exit_code = (
            0
            if result["production_fields_complete"]
            else 2
        )
    elif args.command == "verify-nifty500":
        result = verify_nifty500_snapshot(
            args.file,
            expected_sha256=args.sha256,
        )
        exit_code = 0 if result["production_ready"] else 2
    else:
        result = verify_snapshot(
            args.file,
            expected_sha256=args.sha256,
        )
        exit_code = 0

    print(json.dumps(result, indent=2, default=_json_default))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
