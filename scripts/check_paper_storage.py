"""Read-only durable paper storage diagnostics; never changes recovery flags."""

import json

from services.paper_storage_setup import paper_storage_setup


def main() -> int:
    report = paper_storage_setup()
    print(json.dumps(report, indent=2))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
