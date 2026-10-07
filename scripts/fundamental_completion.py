"""Export, preview, and apply Fundamental Completion workbooks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from core.database import initialize_database
from services.fundamental_completion_service import FundamentalCompletionService


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="TrendForge Fundamental Completion Workflow"
    )
    root.add_argument("--db-path", default=None)
    sub = root.add_subparsers(dest="command", required=True)

    export = sub.add_parser(
        "export",
        help="Create a completion CSV/XLSX from incomplete SQLite records",
    )
    export.add_argument("--out", required=True)
    export.add_argument(
        "--symbols",
        default=None,
        help="Optional comma-separated symbols",
    )
    export.add_argument("--limit", type=int, default=5000)

    for name in ("preview", "apply"):
        cmd = sub.add_parser(
            name,
            help=(
                "Preview a completion file without writes"
                if name == "preview"
                else "Apply only currently missing fields"
            ),
        )
        cmd.add_argument("file")
        cmd.add_argument("--source", default=None)
        cmd.add_argument("--as-of", default=None)
        cmd.add_argument("--sheet", default="Completion")

    history = sub.add_parser("history", help="Show numeric completion history")
    history.add_argument("symbol")
    history.add_argument("--limit", type=int, default=200)

    evidence = sub.add_parser(
        "evidence",
        help="Show standardized source/period evidence",
    )
    evidence.add_argument("symbol")
    evidence.add_argument("--limit", type=int, default=500)
    return root


def _symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None


def main() -> None:
    args = parser().parse_args()
    initialize_database(args.db_path)
    service = FundamentalCompletionService(db_path=args.db_path)

    if args.command == "export":
        output = Path(args.out).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        symbols = _symbols(args.symbols)
        suffix = output.suffix.lower()
        if suffix == ".csv":
            output.write_bytes(
                service.completion_csv(
                    symbols=symbols,
                    limit=args.limit,
                )
            )
        elif suffix in {".xlsx", ".xlsm"}:
            output.write_bytes(
                service.completion_xlsx(
                    symbols=symbols,
                    limit=args.limit,
                )
            )
        else:
            raise SystemExit("--out must end in .csv, .xlsx or .xlsm")
        frame = service.completion_frame(
            symbols=symbols,
            limit=args.limit,
        )
        print(
            json.dumps(
                {
                    "status": "exported",
                    "file": str(output),
                    "rows": int(len(frame)),
                    "columns": list(frame.columns),
                },
                indent=2,
            )
        )
        return

    if args.command in {"preview", "apply"}:
        report = service.process_file(
            args.file,
            apply=args.command == "apply",
            source=args.source,
            as_of=args.as_of,
            sheet_name=args.sheet,
        )
        print(json.dumps(report, indent=2, default=str))
        return

    if args.command == "history":
        print(
            json.dumps(
                {
                    "symbol": args.symbol.upper(),
                    "history": service.history(args.symbol, limit=args.limit),
                },
                indent=2,
                default=str,
            )
        )
        return

    if args.command == "evidence":
        print(
            json.dumps(
                service.evidence(args.symbol, limit=args.limit),
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
