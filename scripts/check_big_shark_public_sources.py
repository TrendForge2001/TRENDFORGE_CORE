"""Observe public source access; never load an owner workbook or broker client."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from providers.big_shark_public import BigSharkPublicProvider, PublicFeedError
from services.big_shark_activity import TZ


def observe(*, provider=None, now=None):
    now = now or datetime.now(UTC)
    provider = provider or BigSharkPublicProvider()
    report = {
        "checked_at": now.isoformat(),
        "owner_data_used": False,
        "broker_orders_allowed": False,
        "sources": {},
    }
    try:
        data = provider.holdings(now=now)
        report["sources"]["MONEYCONTROL"] = {
            "status": "available",
            "investor_count": len(data["investors"]),
            "visible_holding_rows": len(data["rows"]),
            "reporting_period": data["reporting_period"],
            "period_status": data["period_status"],
            "coverage": data["coverage"],
            "document_sha256": data["document_sha256"],
        }
    except PublicFeedError as exc:
        report["sources"]["MONEYCONTROL"] = {"status": "unavailable", "code": exc.code}
    for source in ("NSE_BULK", "NSE_BLOCK"):
        try:
            end = now.astimezone(TZ).date()
            data = provider.trades(
                source=source,
                start=end - timedelta(days=6),
                end=end,
                now=now,
            )
            report["sources"][source] = {
                "status": "available",
                "reported_records": len(data["rows"]),
                "coverage": data["coverage"],
                "source_url": data["source_url"],
                "document_sha256": data["document_sha256"],
            }
        except PublicFeedError as exc:
            report["sources"][source] = {"status": "unavailable", "code": exc.code}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = observe()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, sort_keys=True))
    # This is an availability observation, never a strategy/data-quality PASS.


if __name__ == "__main__":
    main()
