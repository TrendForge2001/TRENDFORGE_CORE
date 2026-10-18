"""Read-only FinEdge candidate export for R71.1 local completion preparation.

Never imports candidates into the scanner. Operator must check period/units,
financial statement families and evidence before completion workbook updates.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from providers.finedge_api_provider import FinEdgeAPIProvider

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


def collect_candidates(
    provider: FinEdgeAPIProvider, symbols: list[str], *, statement_type: str = "c",
) -> dict[str, Any]:
    if len(symbols) > MAX_SYMBOLS_PER_BATCH or not symbols:
        raise ValueError("Batch must contain 1 to 25 symbols")
    if statement_type not in {"c", "s"}:
        raise ValueError("Invalid statement type")
    rows = []
    for symbol in symbols:
        # 4 requests per symbol; the shared limiter includes failed calls.
        # Do not suppress 401/429/503 into zero-valued financial indicators.
        rows.append({
            "symbol": FinEdgeAPIProvider._symbol(symbol),
            "source": "FINEDGE_API",
            "source_url": "https://www.finedgeapi.com/",
            "statement_type": statement_type,
            "verified_for_scanner": False,
            "profitability_ratios": provider.ratios(
                symbol, ratio_type="pr", statement_type=statement_type
            ),
            "leverage_ratios": provider.ratios(
                symbol, ratio_type="le", statement_type=statement_type
            ),
            "growth_metrics": provider.financial_metrics(
                symbol, ratio_type="gr", statement_type=statement_type
            ),
            "shareholding_quarterly": provider.shareholding_pattern(
                symbol, period="quarterly"
            ),
        })
    return {
        "schema_version": "R71.2-candidates-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "field_contract": "raw external observations; not validated as scanner ready",
        "symbols": rows,
        "provider": provider.NAME,
        "api_calls": 4 * len(rows),
    }


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
