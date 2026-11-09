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
    parser.add_argument("--container-image")
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
            command = [
                args.runtime_python,
                "-m",
                "uvicorn",
                "tests.support.research_browser_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ]
            if args.container_image:
                command = [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    f"tf-research-{port}",
                    "--network",
                    "host",
                    "--cpus",
                    "0.15",
                    "--memory",
                    "512m",
                    "--memory-swap",
                    "512m",
                    "--volume",
                    f"{data}:{data}",
                    *[
                        arg
                        for key in env
                        if key.startswith("TRENDFORGE_")
                        or key in {"PORT", "DATABASE_PATH"}
                        for arg in ("--env", key)
                    ],
                    args.container_image,
                    "python",
                    *command[1:],
                ]
            return subprocess.Popen(
                command,
                cwd=repo,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )

        def stop():
            nonlocal process
            if process is not None:
                if args.container_image:
                    subprocess.run(
                        ["docker", "stop", "--time", "10", f"tf-research-{port}"],
                        check=False,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
                else:
                    process.terminate()
                process.wait(timeout=30)
                process = None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, accept_downloads=True
                )
                page.set_default_timeout(120000 if args.container_image else 30000)

                def ready():
                    deadline = time.monotonic() + 180
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
                    page.get_by_label("Manual Access Key (required)", exact=True).fill(
                        access_key
                    )
                    page.get_by_label("Admin API Key (optional)", exact=True).fill(
                        admin_key
                    )
                    page.get_by_role("button", name="Open TrendForge").click()
                    page.get_by_text("Research batches", exact=True).wait_for()
                    assert page.get_by_text("fundamentals", exact=True).count() == 0

                process = start()
                ready()
                signin()
                page.get_by_text("Kite Backtesting", exact=True).click()
                page.get_by_label("Stock list", exact=True).click()
                page.get_by_text("NIFTY 100", exact=True).last.click()
                page.get_by_text("100 stocks ·", exact=False).wait_for()
                page.get_by_role("button", name="Backtest", exact=True).click()
                # Navigation can cancel an unfinished Streamlit rerun. Wait
                # for the backend acknowledgement before leaving the page.
                page.get_by_text(
                    "submitted. Progress and reports are on Reports.", exact=False
                ).wait_for()
                print("BROWSER_DAILY_BATCH_ACKNOWLEDGED=true", flush=True)
                page.get_by_text("Reports", exact=True).first.click()
                headers = {"X-TrendForge-Admin-Key": admin_key}
                deadline = time.monotonic() + 600
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
                    page.wait_for_timeout(1000)
                assert batch is not None and batch["status"] == "completed", {
                    "batch": batch
                    and {
                        key: batch.get(key)
                        for key in (
                            "status",
                            "phase",
                            "phase_completed",
                            "phase_total",
                            "error_code",
                        )
                    }
                }
                page.get_by_role("button", name="Download CSV", exact=True).wait_for(
                    timeout=90000
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
                # The old request pool belongs to the deliberately stopped
                # server. A fresh browser context avoids reusing its dead TCP
                # sockets; do not retry mutations or hide application failures.
                page.close()
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, accept_downloads=True
                )
                page.set_default_timeout(120000 if args.container_image else 30000)
                process = start()
                ready()
                signin()
                page.get_by_role("button", name="Download CSV", exact=True).wait_for(
                    timeout=90000
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
                # Reproduce the user's full intraday workload under Render's
                # actual free-tier CPU/memory quota, while UI/API remain live.
                assert (
                    page.request.post(
                        base + "/fixture/render-batches", headers=headers
                    ).status
                    == 200
                )
                response = page.request.post(
                    base + "/reports/backtest",
                    headers=headers,
                    data={
                        "symbols": [f"S{i:03d}" for i in range(100)],
                        "strategy_id": "tf_ema20_50_bearish_pivot",
                        "horizon": "intraday",
                        "stock_list": "NIFTY 100",
                        "short_borrow_available": True,
                    },
                )
                assert response.status == 202, response.text()
                intraday_id = response.json()["batch_id"]
                assert response.json()["partition_count"] == 3
                deadline = time.monotonic() + 600
                intraday = None
                while time.monotonic() < deadline:
                    started = time.monotonic()
                    assert page.request.get(base + "/livez", timeout=2000).status == 200
                    liveness_samples.append(time.monotonic() - started)
                    response = page.request.get(
                        base + "/reports/batches/" + intraday_id,
                        headers=headers,
                        timeout=3000,
                    )
                    assert response.status == 200
                    intraday = response.json()
                    assert page.get_by_text("Connection error", exact=True).count() == 0
                    if intraday["status"] == "completed":
                        break
                    assert intraday["status"] in {"queued", "running"}, intraday.get(
                        "error_code"
                    )
                    page.wait_for_timeout(1000)
                assert intraday is not None and intraday["status"] == "completed"
                assert intraday["requested_symbols"] == 100
                assert intraday["report"]["mode"] == "intraday"
                assert intraday["report"]["xlsx_sha256"]
                assert (
                    intraday["report"]["report_type"] == "research_partition_manifest"
                )
                assert intraday["report"]["partition_scope"] == "independent_portfolios"
                child_symbols = []
                for row in intraday["report"]["rows"]:
                    child = page.request.get(
                        base + "/reports/batches/" + row["batch_id"], headers=headers
                    ).json()
                    assert child["status"] == "completed"
                    assert len(child["request"]["symbols"]) <= 50
                    assert (
                        child["report"]["report_type"]
                        == "historical_backtest_exit_fills"
                    )
                    child_symbols.extend(child["request"]["symbols"])
                assert child_symbols == [f"S{i:03d}" for i in range(100)]
                browser.close()
                receipt = {
                    "status": "passed",
                    "stocks": 100,
                    "bars_per_stock": 500,
                    "intraday_bars_per_stock": 1125,
                    "intraday_100_stock_bearish_backtest": "passed",
                    "sequential_render_partitions": 3,
                    "runtime_cpu_quota": 0.15 if args.container_image else "host",
                    "runtime_memory_limit_mib": 512 if args.container_image else "host",
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
            server_log = (args.output_dir / "browser-server.txt").read_text()
            diagnostic = [
                line
                for line in server_log.splitlines()
                if any(
                    marker in line
                    for marker in ("POST ", "research_worker", "ERROR", "Traceback")
                )
            ]
            print("\n".join(diagnostic[-30:]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
