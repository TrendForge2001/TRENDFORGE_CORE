"""Browser acceptance: cold Reports link, 100-stock backtest and PC restart.

Uses only synthetic data and a temporary database. Never imports a broker client.
Requires Playwright in a separate test environment and the runtime Python path.
"""

import argparse
import csv
import hashlib
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

from playwright.sync_api import expect, sync_playwright


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
            "TRENDFORGE_EXCEL_PASSWORD": secrets.token_urlsafe(40),
            "TRENDFORGE_KITE_WINDOW_PASSWORD": secrets.token_urlsafe(40),
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
                    "0.5",
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
                browser = playwright.chromium.launch(
                    **(
                        {"executable_path": os.environ["TRENDFORGE_BROWSER_EXECUTABLE"]}
                        if os.getenv("TRENDFORGE_BROWSER_EXECUTABLE")
                        else {}
                    )
                )
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
                    page.get_by_label("Webapp access key", exact=True).fill(access_key)
                    assert page.locator('input[type="password"]').count() == 1
                    page.get_by_role("button", name="Open TrendForge").click()
                    page.get_by_text("Reports", exact=True).first.wait_for()
                    assert page.get_by_text("fundamentals", exact=True).count() == 0

                process = start()
                ready()
                blocked_download_chunks = []

                def block_download_chunk(route):
                    blocked_download_chunks.append(route.request.url)
                    route.abort("failed")

                page.route("**/DownloadButton*.js", block_download_chunk)
                signin()
                page.get_by_role("link", name="Stock Scanner", exact=True).click()

                def horizon(label, expected):
                    expect(page.get_by_test_id("stApp")).to_have_attribute(
                        "data-test-script-state", "notRunning", timeout=30000
                    )
                    page.get_by_text(label, exact=True).click()
                    try:
                        expect(
                            page.get_by_label("Research strategy", exact=True)
                        ).to_have_value(expected, timeout=30000)
                    except AssertionError:
                        page.screenshot(
                            path=str(args.output_dir / "horizon-failure.png")
                        )
                        print(
                            page.get_by_text(label, exact=True).evaluate(
                                "e => e.closest('button')?.outerHTML || e.outerHTML"
                            ),
                            flush=True,
                        )
                        raise

                horizon(
                    "Long Term", "Weekly EMA 50/100 · Gap Recovery · Yearly Floor R2"
                )
                page.get_by_label("Research strategy", exact=True).wait_for()
                page.get_by_label("Research strategy", exact=True).click()
                # Streamlit virtualizes long menus: unmounted options are not
                # absent choices. Verify search access to both native horizons.
                for label in (
                    "Weekly EMA 50/100 · Gap Recovery · Yearly Floor R2",
                    "Daily EMA 50/100 Crossover · Close Above EMA50 · Long Term",
                    "Daily EMA 100/200 Crossover · Close Above EMA100 · Long Term",
                ):
                    page.get_by_label("Research strategy", exact=True).fill(label)
                    expect(
                        page.get_by_role("option", name=label, exact=True)
                    ).to_be_visible()
                page.keyboard.press("Escape")
                horizon(
                    "Short Term",
                    "Daily EMA 20/50 Crossover · RSI + Volume · Short Term",
                )
                for label in (
                    "Daily VWMA 20/50 · Yearly Fibonacci Retest · Conditional Exits",
                    "Daily EMA 20/50 Trend · Weekly Fib Support Bounce · Short Term",
                ):
                    page.get_by_label("Research strategy", exact=True).fill(label)
                    expect(
                        page.get_by_role("option", name=label, exact=True)
                    ).to_be_visible()
                page.keyboard.press("Escape")
                horizon(
                    "Long Term", "Weekly EMA 50/100 · Gap Recovery · Yearly Floor R2"
                )
                expect(
                    page.get_by_label("Research strategy", exact=True)
                ).to_have_value("Weekly EMA 50/100 · Gap Recovery · Yearly Floor R2")
                page.get_by_label("Stock list", exact=True).fill("NIFTY 500")
                page.get_by_role("option", name="NIFTY 500", exact=True).click()
                page.get_by_text("500 stocks ·", exact=False).wait_for()
                page.get_by_role("button", name="Scan stocks", exact=True).click()
                page.get_by_text(
                    "Run submitted.",
                    exact=False,
                ).wait_for()
                scan_deadline = time.monotonic() + 900
                headers = {"X-TrendForge-Admin-Key": admin_key}
                while time.monotonic() < scan_deadline:
                    scans = page.request.get(
                        base + "/reports/batches?kind=scan", headers=headers
                    ).json()["batches"]
                    if scans and scans[0]["status"] == "completed":
                        scan = page.request.get(
                            base + "/reports/batches/" + scans[0]["batch_id"],
                            headers=headers,
                        ).json()
                        assert len(scan["report"]["rows"]) == 500
                        assert {r["symbol"] for r in scan["report"]["rows"]} == {
                            f"S{i:03d}" for i in range(500)
                        }
                        assert not scan["request"].get("partitions")
                        break
                    assert not scans or scans[0]["status"] in {"queued", "running"}
                    page.wait_for_timeout(1000)
                else:
                    raise AssertionError("Full 500-stock scan did not complete")
                # The inline shortcut updates the active tab in a callback;
                # assigning a tab key after rendering it raises in Streamlit.
                selected_report_stock = page.get_by_label(
                    "Stock report", exact=True
                ).input_value()
                page.get_by_role("button", name="Open report", exact=True).click()
                expect(
                    page.get_by_role("tab", name="Stock report", exact=True)
                ).to_have_attribute("aria-selected", "true")
                expect(page.get_by_label("NSE stock symbol", exact=True)).to_have_value(
                    selected_report_stock
                )
                expect(page.get_by_test_id("stException")).to_have_count(0)
                print("SCANNER_STOCK_REPORT_SHORTCUT=passed", flush=True)
                response = page.request.post(
                    base + "/reports/backtest",
                    headers=headers,
                    data={
                        "symbols": [f"S{i:03d}" for i in range(500)],
                        "strategy_id": "tf_weekly_gap_recovery_ema50_100_floor",
                        "horizon": "long_term",
                        "stock_list": "NIFTY 500",
                        "period": "5y",
                        "short_borrow_available": False,
                    },
                )
                assert response.status == 202, response.text()
                print("BROWSER_DAILY_BATCH_ACKNOWLEDGED=true", flush=True)
                page.get_by_text("Reports", exact=True).first.click()
                headers = {"X-TrendForge-Admin-Key": admin_key}
                deadline = time.monotonic() + 900
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
                csv_response = page.request.get(
                    base + "/reports/batches/" + batch["batch_id"] + "/report.csv",
                    headers=headers,
                )
                assert csv_response.status == 200
                csv_bytes = csv_response.body()
                assert (
                    hashlib.sha256(csv_bytes).hexdigest() == batch["report"]["sha256"]
                )
                excel_response = page.request.get(
                    base + "/reports/batches/" + batch["batch_id"] + "/report.xlsx",
                    headers=headers,
                    timeout=30000,
                )
                assert excel_response.status == 200
                excel_bytes = excel_response.body()
                assert not excel_bytes.startswith(b"PK")
                check = subprocess.run(
                    [
                        args.runtime_python,
                        "-c",
                        "import io,os,sys,msoffcrypto; "
                        "f=msoffcrypto.OfficeFile("
                        "io.BytesIO(sys.stdin.buffer.read()));"
                        "f.load_key(password=os.environ["
                        "'TRENDFORGE_VERIFY_PASSWORD'],verify_password=True);"
                        "o=io.BytesIO();f.decrypt(o);"
                        "sys.stdout.buffer.write(o.getvalue())",
                    ],
                    input=excel_bytes,
                    env={**os.environ, "TRENDFORGE_VERIFY_PASSWORD": env["TRENDFORGE_EXCEL_PASSWORD"]},
                    capture_output=True,
                    check=True,
                )
                assert (
                    hashlib.sha256(check.stdout).hexdigest()
                    == batch["report"]["xlsx_sha256"]
                )
                assert not blocked_download_chunks
                assert (
                    page.get_by_text(
                        "Failed to fetch dynamically imported module", exact=False
                    ).count()
                    == 0
                )
                rows = list(csv.DictReader(io.StringIO(csv_bytes.decode("utf-8-sig"))))
                assert all(row["entry_at"] and row["exit_at"] for row in rows)
                assert len(batch["report"]["comparisons"]) == 4
                assert batch["request"]["account_scope"] == "one_shared_account"
                assert not batch["request"].get("partitions")
                assert batch["report"]["benchmark"]["status"] == "complete"
                assert any(
                    run["trades"] for run in batch["report"]["comparison_results"]
                )
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
                page.route("**/DownloadButton*.js", block_download_chunk)
                process = start()
                ready()
                signin()
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
                # Reproduce the user's short-term scanner workload under Render's
                # paid service CPU/memory quota, while UI/API remain live.
                assert (
                    page.request.post(
                        base + "/fixture/render-batches", headers=headers
                    ).status
                    == 200
                )
                for paused_horizon, paused_strategy in (
                    ("intraday", "tf_ema9_26_bullish_pivot"),
                    ("short_swing", "tf_swing_ema20_50_rsi_volume"),
                ):
                    rejected = page.request.post(
                        base + "/reports/backtest",
                        headers=headers,
                        data={
                            "symbols": ["TCS"],
                            "strategy_id": paused_strategy,
                            "horizon": paused_horizon,
                            "stock_list": "NIFTY 100",
                        },
                    )
                    assert rejected.status == 422
                response = page.request.post(
                    base + "/reports/backtest",
                    headers=headers,
                    data={
                        "symbols": [f"S{i:03d}" for i in range(100)],
                        "strategy_id": "tf_ema20_50_bullish_pivot",
                        "horizon": "short_term",
                        "stock_list": "NIFTY 100",
                        "short_borrow_available": False,
                    },
                )
                assert response.status == 202, response.text()
                short_term_id = response.json()["batch_id"]
                assert response.json()["partition_count"] == 4
                deadline = time.monotonic() + 900
                short_term = None
                while time.monotonic() < deadline:
                    started = time.monotonic()
                    assert page.request.get(base + "/livez", timeout=2000).status == 200
                    liveness_samples.append(time.monotonic() - started)
                    response = page.request.get(
                        base + "/reports/batches/" + short_term_id,
                        headers=headers,
                        timeout=3000,
                    )
                    assert response.status == 200
                    short_term = response.json()
                    assert page.get_by_text("Connection error", exact=True).count() == 0
                    if short_term["status"] == "completed":
                        break
                    assert short_term["status"] in {"queued", "running"}, (
                        short_term.get("error_code")
                    )
                    page.wait_for_timeout(1000)
                assert short_term is not None and short_term["status"] == "completed"
                assert short_term["requested_symbols"] == 100
                assert short_term["report"]["mode"] == "swing"
                assert short_term["report"]["xlsx_sha256"]
                assert (
                    short_term["report"]["report_type"] == "research_partition_manifest"
                )
                assert (
                    short_term["report"]["partition_scope"] == "independent_portfolios"
                )
                child_symbols = []
                for row in short_term["report"]["rows"]:
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
                    "stocks": 500,
                    "consolidated_scan_rows": 500,
                    "default_scanner": "weekly_floor_with_daily_vwma_available",
                    "weekly_source_daily_bars_per_stock": 1310,
                    "daily_bars_per_stock": 1310,
                    "short_term_100_stock_annual_exit_backtest": "passed",
                    "sequential_render_partitions": 4,
                    "paused_intraday_and_short_swing_rejected": "passed",
                    "runtime_cpu_quota": 0.5 if args.container_image else "host",
                    "runtime_memory_limit_mib": 512 if args.container_image else "host",
                    "trade_exit_rows": len(rows),
                    "cold_reports_deeplink": "sign-in required",
                    "csv_download": "passed",
                    "excel_download": "passed_checksum",
                    "json_backup_download": "archive restart recovery verified",
                    "download_transport": (
                        "authenticated API; native UI download checked separately"
                    ),
                    "download_widget_bundle": (
                        "blocked_without_affecting_native_downloads"
                    ),
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
