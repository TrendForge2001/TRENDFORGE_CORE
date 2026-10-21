"""R72.5.7: offline, read-only deployment contract preflight.

Usage: python -m scripts.r7257_deployment_preflight [--root PATH]
Never contacts providers, mutates databases, or submits orders.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def inspect(root: Path) -> dict:
    checks = {}
    render = root / "render.yaml"
    lock = root / "requirements-production.lock"
    runtime = root / ".python-version"
    start = root / "start.py"
    checks["render_exists"] = render.is_file()
    checks["lock_exists"] = lock.is_file() and bool(lock.read_text(encoding="utf-8").strip())
    checks["runtime_exists"] = runtime.is_file()
    checks["entrypoint_exists"] = start.is_file()
    if checks["render_exists"]:
        config = render.read_text(encoding="utf-8")
        checks["healthcheck_livez"] = "healthCheckPath: /livez" in config
        checks["locked_install"] = "pip install -r requirements-production.lock" in config
        checks["uvicorn_start"] = "uvicorn start:app" in config
    else:
        checks.update(healthcheck_livez=False, locked_install=False, uvicorn_start=False)
    if checks["runtime_exists"]:
        checks["python_312"] = runtime.read_text(encoding="utf-8").strip().startswith("3.12")
    else:
        checks["python_312"] = False
    if checks["entrypoint_exists"]:
        source = start.read_text(encoding="utf-8")
        checks["livez_declared"] = '"/livez"' in source or "'/livez'" in source
    else:
        checks["livez_declared"] = False
    return {
        "batch": "R72.5.7",
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "failed": sorted(key for key, passed in checks.items() if not passed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = inspect(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
