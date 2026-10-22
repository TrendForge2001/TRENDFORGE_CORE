"""Read-only post-deploy verification of the exact Render release commit."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any, cast

from scripts.production_readonly_acceptance import safe_base_url


def probe_once(base: str, expected_sha: str, *, opener: Any = None) -> dict[str, Any]:
    open_request = opener or urllib.request.urlopen
    report: dict[str, Any] = {"deployed_sha": None}
    for name, path in (
        ("liveness", "/livez"),
        ("ui", "/app/"),
        ("release", "/production/health"),
    ):
        try:
            request = urllib.request.Request(base + path, method="GET")
            with open_request(request, timeout=10) as response:
                report[name] = response.status
                if name == "release" and response.status == 200:
                    raw = response.read(100_001)
                    if len(raw) > 100_000:
                        raise ValueError("Oversized response")
                    data: object = json.loads(raw)
                    body = (
                        cast(dict[str, object], data) if isinstance(data, dict) else {}
                    )
                    deployment = body.get("deployment")
                    deployment_body = (
                        cast(dict[str, object], deployment)
                        if isinstance(deployment, dict)
                        else {}
                    )
                    sha = deployment_body.get("render_git_commit")
                    if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
                        report["deployed_sha"] = sha
        except urllib.error.HTTPError as exc:
            report[name] = exc.code
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            report[name] = "unavailable"
    report["verified"] = (
        all(report.get(name) == 200 for name in ("liveness", "ui", "release"))
        and report["deployed_sha"] == expected_sha
    )
    return report


def wait_for_deployment(
    base: str,
    expected_sha: str,
    *,
    timeout: float = 600,
    interval: float = 15,
    opener: Any = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    base = safe_base_url(base)
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise ValueError("Expected a full Git commit SHA")
    deadline = clock() + max(0, timeout)
    previous = None
    while True:
        report = probe_once(base, expected_sha, opener=opener)
        state = json.dumps(report, sort_keys=True)
        if state != previous:
            print(state, flush=True)
            previous = state
        if report["verified"]:
            print(
                f"::notice title=Render deployment::Verified release {expected_sha}",
                flush=True,
            )
            return True
        if clock() >= deadline:
            print(
                f"::error title=Render deployment::Release {expected_sha} "
                f"not verified; last state {state}",
                flush=True,
            )
            return False
        sleep(max(0.0, min(max(0.1, interval), 30, deadline - clock())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://trendforge-core.onrender.com")
    parser.add_argument("--sha", required=True)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args()
    return 0 if wait_for_deployment(args.base, args.sha, timeout=args.timeout) else 1


if __name__ == "__main__":
    raise SystemExit(main())
