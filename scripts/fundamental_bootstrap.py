"""Export, verify or restore TrendForge fundamental bootstrap bundles."""
from __future__ import annotations

import argparse
import json

from core.database import initialize_database
from services.bootstrap_format import read_verified_bundle
from services.fundamental_bootstrap_service import FundamentalBootstrapService


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export")
    export.add_argument("--out", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("file")
    verify.add_argument("--sha256", default=None)

    apply = sub.add_parser("apply")
    apply.add_argument("file")
    apply.add_argument("--sha256", default=None)

    args = parser.parse_args()
    if args.command == "verify":
        bundle, meta = read_verified_bundle(
            args.file,
            expected_file_sha256=args.sha256,
            require_pinned_sha256=bool(args.sha256),
        )
        result = {
            "status": "verified",
            **meta,
            "fundamental_records": len(bundle["fundamentals"]),
            "evidence_records": len(bundle["evidence"]),
            "field_update_records": len(bundle["field_updates"]),
        }
    else:
        initialize_database(args.db_path)
        service = FundamentalBootstrapService(db_path=args.db_path)
        try:
            if args.command == "export":
                result = service.export_bundle(args.out)
            else:
                result = service.apply_bundle(
                    args.file,
                    expected_file_sha256=args.sha256,
                    require_pinned_sha256=bool(args.sha256),
                )
        finally:
            service.close()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
