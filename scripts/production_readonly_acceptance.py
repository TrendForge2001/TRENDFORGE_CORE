"""R72.5.8.3: non-mutating production acceptance probe.

Usage:
  python -m scripts.production_readonly_acceptance --base https://trendforge-core.onrender.com

Only GET requests are made. Never supply admin keys on the command line.
Optional TRENDFORGE_ADMIN_API_KEY is used only as an HTTP header; not printed.
Exit code 0 means all mandatory liveness/read probes succeeded; blocked gates
remain explicitly unverified and are never silently marked as passed.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PATHS = (
    "/livez",
    "/app/",
    "/production/health",
    "/technical/multi-strategy/readiness",
    "/technical/multi-strategy/status",
    "/technical/multi-strategy/results",
    "/watchlists",
)
MAX_BYTES = 2_000_000


def safe_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Production probe requires an HTTPS base URL without credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Base URL must not contain path, query, or fragment")
    return value.rstrip("/")


def probe(base_url: str, *, opener: Any = None, admin_key: str | None = None) -> dict[str, Any]:
    base = safe_base_url(base_url)
    open_request = opener or urllib.request.urlopen
    checks: list[dict[str, Any]] = []
    for path in PATHS:
        headers = {"Accept": "application/json"}
        if admin_key and path not in ("/livez", "/app/"):
            headers["X-TrendForge-Admin-Key"] = admin_key
        request = urllib.request.Request(base + path, headers=headers, method="GET")
        try:
            with open_request(request, timeout=20) as response:
                status = response.status
                payload = response.read(MAX_BYTES + 1)
                if len(payload) > MAX_BYTES:
                    raise ValueError("Response exceeds safety limit")
                data = json.loads(payload) if payload and "json" in response.headers.get("Content-Type", "") else None
            check: dict[str, Any] = {"path": path, "http_status": status, "ok": status == 200}
            if path == "/technical/multi-strategy/status" and isinstance(data, dict):
                check["scanner_status"] = str(data.get("status", "unknown"))[:80]
            if path == "/technical/multi-strategy/results" and isinstance(data, dict):
                check["has_results"] = bool(data.get("results") or data.get("last_result"))
            if path == "/production/health" and isinstance(data, dict):
                storage = data.get("storage")
                if isinstance(storage, dict):
                    check["storage_status"] = str(storage.get("status", "unknown"))[:80]
                    check["durability_verified"] = bool(storage.get("verified_persistent", False))
            checks.append(check)
        except urllib.error.HTTPError as exc:
            checks.append({"path": path, "http_status": exc.code, "ok": False, "error": "HTTP error"})
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            checks.append({"path": path, "http_status": None, "ok": False, "error": type(exc).__name__})
    return {
        "mode": "read_only",
        "requests": len(checks),
        "checks": checks,
        "all_read_probes_ok": all(c["ok"] for c in checks),
        "not_verified": [
            "Kite authenticated candle completeness and token freshness",
            "NIFTY 100 selector browser interaction",
            "Controlled scanner run and symbol accounting",
            "SQLite persistent disk mount and restart recovery",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://trendforge-core.onrender.com")
    args = parser.parse_args()
    result = probe(args.base, admin_key=os.getenv("TRENDFORGE_ADMIN_API_KEY"))
    print(json.dumps(result, indent=2))
    return 0 if result["all_read_probes_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
