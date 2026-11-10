"""Read-only fixed-egress evidence. Run on the execution host, not the laptop."""

import argparse
import json

from services.kite_network_readiness import kite_network_readiness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe", action="store_true", help="Sample the configured route"
    )
    args = parser.parse_args()
    report = kite_network_readiness(probe=args.probe)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "observed_ips_match_configuration" else 1


if __name__ == "__main__":
    raise SystemExit(main())
