"""Read-only FinEdge candidate export for R71.1 local completion preparation.

Never imports candidates into the scanner. Operator must check period/units,
financial statement families and evidence before completion workbook updates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from providers.finedge_api_provider import FinEdgeAPIProvider
from services.finedge_fundamental_service import (
    collect_fundamental_observations as collect_candidates,
)

MAX_SYMBOLS_PER_BATCH = 25


def normalize_symbols(csv_symbols: str) -> list[str]:
    symbols = []
    for value in str(csv_symbols).split(","):
        text = FinEdgeAPIProvider._symbol(value)
        if text not in symbols:
            symbols.append(text)
    if not symbols or len(symbols) > MAX_SYMBOLS_PER_BATCH:
        raise ValueError("Request 1 to 25 unique symbols in a batch")
    return symbols


def exclusive_json_write(path: Path, payload: dict[str, Any]) -> None:
    target = path.expanduser().resolve()
    # Exclusive create: never overwrite a prior evidence candidate export.
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(payload, file, indent=2, ensure_ascii=False)
            file.write("\n")
    except Exception:
        target.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="FinEdge data candidate export; never changes SQLite"
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated NSE tickers")
    parser.add_argument("--statement-type", choices=["c", "s"], default="c")
    parser.add_argument("--collect", action="store_true",
                        help="Explicitly use API and export candidates")
    parser.add_argument("--out", help="New JSON file; may not already exist")
    args = parser.parse_args(argv)
    try:
        symbols = normalize_symbols(args.symbols)
        provider = FinEdgeAPIProvider.from_env()
        planned = {
            "status": "plan_only",
            "symbols": symbols,
            "request_count": len(symbols) * 4,
            "configured": provider.health(),
            "writes_to_database": False,
        }
        if not args.collect:
            print(json.dumps(planned, indent=2))
            return 0
        if not args.out:
            raise ValueError("--collect requires --out")
        if not provider.enabled or not provider.api_key:
            raise ValueError("Set server-side FINEDGE_ENABLED=true and FINEDGE_API_KEY")
        output = Path(args.out).expanduser()
        if output.exists():
            raise FileExistsError(f"Candidate output already exists: {output}")
        data = collect_candidates(provider, symbols, statement_type=args.statement_type)
        exclusive_json_write(output, data)
        print(json.dumps({
            "status": "exported_unverified_candidates",
            "file": str(output),
            "symbols": len(symbols),
            "api_calls": data["api_calls"],
            "database_changed": False,
        }, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        # Never print request URLs, because query params carry credentials.
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
