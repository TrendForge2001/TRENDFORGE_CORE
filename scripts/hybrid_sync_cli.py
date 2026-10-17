"""Manual local R70.3 outbox commands. No automatic sending."""
from __future__ import annotations

import argparse
import json
import sys
from services.hybrid_sync_service import LocalOutbox, send_once, utc_now


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TrendForge hybrid sync")
    parser.add_argument("command", choices=("status", "queue-heartbeat", "send-once"))
    args = parser.parse_args(argv)
    try:
        outbox = LocalOutbox.from_environment()
        if args.command == "status":
            result = {"status": "ready", **outbox.status(), "network_enabled": False}
        elif args.command == "queue-heartbeat":
            event_id = outbox.enqueue(
                "heartbeat",
                {"component": "windows_observer", "state": "ready",
                 "observed_at_utc": utc_now(), "trading_enabled": False},
            )
            result = {"status": "queued", "event_id": event_id, **outbox.status()}
        else:
            result = {"status": "attempted", **send_once(outbox)}
    except Exception as exc:
        # Never print dynamic messages which might contain endpoints or credentials.
        result = {"status": "blocked", "reason": type(exc).__name__}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] != "blocked" else 1


if __name__ == "__main__":
    sys.exit(main())
