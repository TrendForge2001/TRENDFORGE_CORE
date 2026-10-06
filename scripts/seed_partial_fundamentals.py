"""Preview/apply partial fundamentals from legacy CSV/XLSX workbooks."""
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
from services.fundamental_partial_seed_service import FundamentalPartialSeedService


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Safely seed partial fundamentals from legacy CSV/XLSX/XLSM files. "
            "Default mode is preview; use --apply to write resolved valid rows."
        )
    )
    result.add_argument("file", help="Legacy fundamentals workbook/CSV")
    result.add_argument("--apply", action="store_true", help="Write resolved valid rows to SQLite")
    result.add_argument("--source", default="legacy_partial_seed")
    result.add_argument("--identifier-column", default=None)
    result.add_argument(
        "--field-map",
        default=None,
        help="JSON mapping of canonical fields to source column names",
    )
    result.add_argument(
        "--symbol-map",
        default=None,
        help="Optional JSON/CSV/XLSX mapping of company Name -> Symbol",
    )
    result.add_argument("--sheet", default="0")
    result.add_argument("--as-of", default=None)
    result.add_argument("--db-path", default=None)
    result.add_argument(
        "--unresolved-out",
        default=None,
        help="Optional CSV/XLSX path for unresolved Name -> Symbol mapping template",
    )
    return result


def _write_unresolved(service, report, output: str | None) -> str | None:
    if not output or not report.get("unresolved_rows"):
        return None
    path = Path(output).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = service.unresolved_mapping_frame(report)
    if path.suffix.lower() == ".csv":
        frame.to_csv(path, index=False)
    elif path.suffix.lower() in {".xlsx", ".xlsm"}:
        frame.to_excel(path, index=False)
    else:
        raise ValueError("--unresolved-out must end in .csv, .xlsx or .xlsm")
    return str(path)


def main() -> None:
    args = parser().parse_args()
    initialize_database(args.db_path)
    service = FundamentalPartialSeedService(db_path=args.db_path)
    report = service.process_file(
        args.file,
        apply=args.apply,
        source=args.source,
        identifier_column=args.identifier_column,
        field_map=args.field_map,
        symbol_map=args.symbol_map,
        sheet_name=args.sheet,
        as_of=args.as_of,
    )
    unresolved_path = _write_unresolved(
        service,
        report,
        args.unresolved_out,
    )
    if unresolved_path:
        report["unresolved_mapping_template"] = unresolved_path
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
