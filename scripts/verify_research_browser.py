"""Browser acceptance: cold Reports link, 100-stock backtest and PC restart.

Uses only synthetic data and a temporary database. Never imports a broker client.
Requires Playwright in a separate test environment and the runtime Python path.
"""

import argparse
import csv
import io
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="trendforge-browser-") as folder:
        data = Path(folder)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        access_key, admin_key = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            "PORT": str(port),
            "DATABASE_PATH": str(data / "database" / "trendforge.db"),
            "TRENDFORGE_DATA_DIR": str(data),
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
            "TRENDFORGE_ADMIN_API_KEY": admin_key,
            "TRENDFORGE_WEBAPP_ACCESS_KEY": access_key,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
        }
        process = None
        log = (args.output_dir / "browser-server.txt").open("w")

        def start():
            return subprocess.Popen(
                [
                    args.runtime_python,
                    "-m",
                    "uvicorn",
                    "tests.support.research_browser_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=repo,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        def stop():
            nonlocal process
            if process is not None:
                process.terminate()
                process.wait(timeout=20)
                process = None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, accept_downloads=True
                )
                page.set_default_timeout(30000)

                def ready():
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        try:
                            if (
                                page.request.get(base + "/livez", timeout=1000).status
                                == 200
                            ):
                                return
                        except Exception:
                            pass
                        time.sleep(0.2)
                    raise AssertionError("Synthetic browser server did not start")

                def signin():
                    page.goto(base + "/app/reports")
                    page.get_by_label("Manual Access Key (required)").fill(access_key)
                    page.get_by_label("Admin API Key (optional)").fill(admin_key)
                    page.get_by_role("button", name="Open TrendForge").click()
                    page.get_by_text("Research batches", exact=True).wait_for()
                    assert page.get_by_text("fundamentals", exact=True).count() == 0

                process = start()
                ready()
                signin()
                page.get_by_text("Kite Backtesting", exact=True).click()
                page.get_by_label("Stock list").click()
                page.get_by_text("NIFTY 100", exact=True).last.click()
                page.get_by_role("button", name="Backtest", exact=True).click()
                page.get_by_text("Reports", exact=True).first.click()
                headers = {"X-TrendForge-Admin-Key": admin_key}
                deadline = time.monotonic() + 120
                batch = None
                liveness_samples = []
                while time.monotonic() < deadline:
                    started = time.monotonic()
                    assert page.request.get(base + "/livez", timeout=2000).status == 200
                    liveness_samples.append(time.monotonic() - started)
                    response = page.request.get(
                        base + "/reports/batches", headers=headers
                    )
                    assert response.status == 200
                    rows = response.json()["batches"]
                    if rows:
                        batch = page.request.get(
                            base + "/reports/batches/" + rows[0]["batch_id"],
                            headers=headers,
                        ).json()
                        if batch["status"] == "completed":
                            break
                        assert batch["status"] in {"queued", "running"}, batch.get(
                            "error_code"
                        )
                    time.sleep(0.2)
                assert batch is not None and batch["status"] == "completed"
                page.get_by_role("button", name="Download CSV", exact=True).wait_for(
                    timeout=20000
                )
                page.get_by_role(
                    "button", name="Download Excel (.xlsx)", exact=True
                ).wait_for()
                with page.expect_download() as downloaded:
                    page.get_by_role("button", name="Download CSV", exact=True).click()
                rows = list(
                    csv.DictReader(
                        io.StringIO(
                            Path(downloaded.value.path()).read_text(
                                encoding="utf-8-sig"
                            )
                        )
                    )
                )
                assert rows and all(row["entry_at"] and row["exit_at"] for row in rows)
                page.screenshot(
                    path=str(args.output_dir / "completed-report.png"), full_page=True
                )
                batch_id = batch["batch_id"]
                expected = batch["report"]["sha256"]
                stop()
                # Remove only this test's report indexes to prove file recovery.
                with sqlite3.connect(env["DATABASE_PATH"]) as connection:
                    connection.execute("DELETE FROM research_batches")
                    connection.execute("DELETE FROM backtest_results")
                process = start()
                ready()
                signin()
                page.get_by_role("button", name="Download CSV", exact=True).wait_for(
                    timeout=20000
                )
                saved = page.request.get(
                    base + "/reports/batches/" + batch_id, headers=headers
                ).json()
                assert (
                    saved["status"] == "completed"
                    and saved["report"]["sha256"] == expected
                )
                page.screenshot(
                    path=str(args.output_dir / "restored-report.png"), full_page=True
                )
                browser.close()
                receipt = {
                    "status": "passed",
                    "stocks": 100,
                    "bars_per_stock": 500,
                    "trade_exit_rows": len(rows),
                    "cold_reports_deeplink": "sign-in required",
                    "csv_download": "passed",
                    "excel_button": "visible",
                    "restart_file_recovery": "passed",
                    "liveness_max_seconds": max(liveness_samples),
                    "broker_orders": 0,
                }
                (args.output_dir / "browser-verification.json").write_text(
                    json.dumps(receipt, indent=2)
                )
                print(json.dumps(receipt))
        finally:
            stop()
            log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
