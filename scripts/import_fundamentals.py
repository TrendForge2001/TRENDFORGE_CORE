"""Import periodic fundamental-data exports into TrendForge SQLite."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Support both:
#   python -m scripts.import_fundamentals ...
#   python scripts/import_fundamentals.py ...
if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

from core.database import initialize_database
from services.fundamental_data_manager import FundamentalDataManager


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Import CSV/XLSX/XLSM fundamentals into TrendForge SQLite."
    )
    result.add_argument("file", help="Path to the exported fundamentals file")
    result.add_argument("--source", default="manual_file", help="Source label, e.g. screener, tijori or manual")
    result.add_argument("--symbol-column", default=None)
    result.add_argument(
        "--field-map",
        default=None,
        help="JSON mapping of canonical fields to export column names",
    )
    result.add_argument("--sheet", default="0", help="Excel sheet name or zero-based index")
    result.add_argument("--as-of", default=None, help="Snapshot date/time override")
    result.add_argument("--db-path", default=None, help="SQLite path override")
    return result


def main() -> None:
    args = parser().parse_args()
    initialize_database(args.db_path)
    manager = FundamentalDataManager(db_path=args.db_path)
    report = manager.import_file(
        args.file,
        source=args.source,
        symbol_column=args.symbol_column,
        field_map=args.field_map,
        sheet_name=args.sheet,
        as_of=args.as_of,
    )
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
