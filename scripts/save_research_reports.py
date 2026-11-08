"""Copy completed cloud reports to PC files, or import downloaded batch backups.

Only existing report GET endpoints are used. No scans or orders are submitted.
The cloud admin key is read from an environment variable or a hidden prompt.
"""

import argparse
import getpass
import json
import os
import re
import time
from pathlib import Path

import requests

from scripts.production_readonly_acceptance import safe_base_url
from services.research_archive import MAX_BATCH_BYTES, ResearchArchive


def copy_reports(base, archive, *, admin_key, session=None):
    base = safe_base_url(base)
    if not admin_key:
        raise ValueError("A cloud Admin API Key is required")
    session = session or requests.Session()
    headers = {"X-TrendForge-Admin-Key": admin_key, "Accept": "application/json"}

    def read(path, **params):
        with session.get(
            base + path,
            params=params,
            headers=headers,
            timeout=30,
            allow_redirects=False,
            stream=True,
        ) as response:
            if response.status_code != 200:
                raise ValueError(
                    f"Cloud report read failed: HTTP {response.status_code}"
                )
            content = bytearray()
            for chunk in response.iter_content(65536):
                content.extend(chunk)
                if len(content) > MAX_BATCH_BYTES:
                    raise ValueError("Cloud report exceeds the maximum backup size")
            return json.loads(content)

    saved, unfinished, offset = 0, 0, 0
    while True:
        rows = read("/reports/batches", limit=100, offset=offset).get("batches")
        if not isinstance(rows, list):
            raise ValueError("Invalid cloud report history")
        for row in rows:
            if row.get("status") != "completed":
                unfinished += 1
                continue
            batch_id = row["batch_id"]
            # Validate the identifier before it can form a URL path.
            if not isinstance(batch_id, str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,120}", batch_id
            ):
                raise ValueError("Invalid cloud batch identifier")
            target = archive._target(batch_id) / "batch.json"
            if target.is_file():
                archive.read(target)
                continue
            batch = read("/reports/batches/" + batch_id)
            archive.save(batch)
            saved += 1
        if len(rows) < 100:
            return {"saved": saved, "unfinished": unfinished}
        offset += 100


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="https://trendforge-core.onrender.com")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.getenv("LOCALAPPDATA", str(Path.home()))) / "TrendForgeCore",
    )
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Copy newly completed reports every 30 seconds while this PC stays awake",
    )
    args = parser.parse_args()
    archive = ResearchArchive(args.data_dir / "reports" / "research")
    if args.file:
        for path in args.file:
            archive.save(archive.read(path))
        print(
            json.dumps({"imported": len(args.file), "report_folder": str(archive.root)})
        )
        return 0
    key = (
        os.getenv("TRENDFORGE_CLOUD_ADMIN_API_KEY", "").strip()
        or getpass.getpass("Cloud Admin API Key (hidden): ").strip()
    )
    try:
        while True:
            result = copy_reports(args.base, archive, admin_key=key)
            print(
                json.dumps({**result, "report_folder": str(archive.root)}), flush=True
            )
            if not args.watch:
                return 0
            time.sleep(30)
    except KeyboardInterrupt:
        return 0
    except (requests.RequestException, OSError, ValueError, KeyError, TypeError):
        print(
            "Report backup failed. Check the cloud admin key, connection "
            "and available PC disk space; existing files were retained."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
