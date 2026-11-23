"""Synthetic scanner → queue → encrypted Excel, plus Kite reauthentication."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def fixture_status(page, base, headers):
    # Uvicorn may close an idle keepalive while browser navigation completes.
    # Retry only this read-only fixture request; functional assertions stay strict.
    for attempt in range(3):
        try:
            response = page.request.get(base + "/fixture/status", headers=headers)
            assert response.status == 200
            return response.json()
        except Exception as exc:
            if "ECONNRESET" not in str(exc) or attempt == 2:
                raise
            time.sleep(0.1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix="tf-workflow-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        access, admin = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            "DATABASE_PATH": folder + "/book.db",
            "TRENDFORGE_DATA_DIR": folder,
            "TRENDFORGE_WEBAPP_ACCESS_KEY": access,
            "TRENDFORGE_ADMIN_API_KEY": admin,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
            "TRENDFORGE_PRODUCTION_RUNTIME": "false",
            "PORT": str(port),
        }
        with (args.output_dir / "server.txt").open("w") as log:
            server = subprocess.Popen(
                [
                    args.runtime_python,
                    "-m",
                    "uvicorn",
                    "tests.support.design_browser_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=root,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with sync_playwright() as pw:
                    launch = (
                        {"executable_path": os.environ["TRENDFORGE_BROWSER_EXECUTABLE"]}
                        if os.getenv("TRENDFORGE_BROWSER_EXECUTABLE")
                        else {}
                    )
                    browser = pw.chromium.launch(**launch)
                    base, headers = (
                        f"http://127.0.0.1:{port}",
                        {"X-TrendForge-Admin-Key": admin},
                    )
                    for device, width, height in (
                        ("laptop", 1440, 1000),
                        ("mobile", 390, 844),
                    ):
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            is_mobile=device == "mobile",
                            accept_downloads=True,
                        )
                        page = context.new_page()
                        page.set_default_timeout(30000)
                        for _ in range(100):
                            try:
                                if (
                                    page.request.get(
                                        base + "/livez", timeout=1000
                                    ).status
                                    == 200
                                ):
                                    break
                            except Exception:
                                pass
                            time.sleep(0.2)
                        assert (
                            page.request.post(
                                base + "/fixture/workflow/seed", headers=headers
                            ).status
                            == 200
                        )
                        before = fixture_status(page, base, headers)
                        page.goto(base + "/owner/" + device + "?next=/app/")
                        page.get_by_label("Webapp access key", exact=True).fill(access)
                        page.get_by_role(
                            "button", name="Open TrendForge", exact=True
                        ).click()
                        expect(
                            page.get_by_label("Stock list", exact=True)
                        ).to_have_count(1, timeout=30000)
                        expect(
                            page.get_by_role("link", name="Watchlists", exact=True)
                        ).to_have_count(0)
                        page.get_by_label("Stock list", exact=True).fill("INDIA VIX")
                        page.get_by_role("option", name="INDIA VIX", exact=True).click()
                        expect(
                            page.get_by_text("This is a reference index", exact=False)
                        ).to_be_visible()
                        expect(
                            page.get_by_role("button", name="Scan stocks", exact=True)
                        ).to_have_count(0)
                        page.get_by_label("Stock list", exact=True).fill(
                            "NIFTY CHEMICALS"
                        )
                        expect(
                            page.get_by_role(
                                "option", name="NIFTY CHEMICALS", exact=True
                            )
                        ).to_be_visible()
                        page.keyboard.press("Escape")
                        if device == "mobile":
                            page.goto(base + "/app/reports")
                        else:
                            page.get_by_role("link", name="Reports", exact=True).click()
                        expect(
                            page.get_by_label("Stock list", exact=True)
                        ).to_have_count(0)
                        expect(page.get_by_test_id("stDataFrame")).to_have_count(1)
                        saved = page.request.get(
                            base + "/reports/scanner-runs/workflow-browser-seed",
                            headers=headers,
                        ).json()
                        assert {row["signal"] for row in saved["rows"]} == {
                            "BUY",
                            "EXIT",
                            "WAIT",
                        }
                        page.screenshot(
                            path=str(args.output_dir / (device + "-reports.png"))
                        )
                        if device == "mobile":
                            page.goto(base + "/app/kite_backtesting")
                        else:
                            page.get_by_role(
                                "link", name="Backtesting", exact=True
                            ).click()
                        expect(
                            page.get_by_label("Stock list", exact=True)
                        ).to_have_count(0)
                        snapshot = page.request.get(
                            base + "/reports/backtest-queue", headers=headers
                        ).json()
                        if snapshot["pending_stocks"]:
                            page.get_by_role(
                                "button", name="Backtest queued stocks", exact=True
                            ).click()
                        deadline = time.monotonic() + 120
                        while time.monotonic() < deadline:
                            snapshot = page.request.get(
                                base + "/reports/backtest-queue", headers=headers
                            ).json()
                            if (
                                snapshot["jobs"]
                                and snapshot["jobs"][0]["status"] == "completed"
                            ):
                                break
                            page.wait_for_timeout(500)
                        assert snapshot["jobs"][0]["status"] == "completed", snapshot[
                            "jobs"
                        ]
                        page.reload()
                        page.get_by_role(
                            "button", name="Prepare encrypted Excel", exact=True
                        ).click()
                        link = page.get_by_role(
                            "link", name="Download protected trade details", exact=True
                        )
                        with page.expect_download() as receipt:
                            link.click()
                        path = args.output_dir / (device + "-protected-trades.xlsx")
                        receipt.value.save_as(path)
                        assert not path.read_bytes().startswith(b"PK")
                        checked = subprocess.run(
                            [
                                args.runtime_python,
                                "-c",
                                "import io,os,sys,msoffcrypto,openpyxl; "
                                "f=msoffcrypto.OfficeFile("
                                "io.BytesIO(sys.stdin.buffer.read()));"
                                "f.load_key(password=os.environ["
                                "'TRENDFORGE_VERIFY_PASSWORD'],verify_password=True);"
                                "o=io.BytesIO();f.decrypt(o);"
                                "w=openpyxl.load_workbook(o,read_only=True);"
                                "assert 'Queued stock strategies' in w.sheetnames;"
                                "assert len(list(w['Queued stock strategies']"
                                ".values))==3;"
                                "print('protected_evidence_verified')",
                            ],
                            input=path.read_bytes(),
                            env={**os.environ, "TRENDFORGE_VERIFY_PASSWORD": access},
                            capture_output=True,
                            check=True,
                        )
                        assert b"protected_evidence_verified" in checked.stdout
                        page.screenshot(
                            path=str(args.output_dir / (device + "-backtesting.png"))
                        )
                        if device == "mobile":
                            page.goto(base + "/app/live_kite")
                        else:
                            page.get_by_role(
                                "link", name="Kite Connection", exact=True
                            ).click()
                        expect(
                            page.get_by_label("Kite window password", exact=True)
                        ).to_be_visible()
                        page.get_by_label("Kite window password", exact=True).fill(
                            "wrong-password"
                        )
                        page.get_by_role(
                            "button", name="Unlock Kite window", exact=True
                        ).click()
                        expect(
                            page.get_by_text("Unable to unlock.", exact=False)
                        ).to_be_visible()
                        expect(
                            page.get_by_label("Kite window password", exact=True)
                        ).to_have_value("")
                        page.get_by_label("Kite window password", exact=True).fill(
                            access
                        )
                        page.get_by_role(
                            "button", name="Unlock Kite window", exact=True
                        ).click()
                        expect(
                            page.get_by_role(
                                "button", name="Lock Kite window", exact=True
                            )
                        ).to_be_visible()
                        expect(
                            page.get_by_label("Stock list", exact=True)
                        ).to_have_count(0)
                        assert fixture_status(page, base, headers) == before
                        assert not page.evaluate(
                            "document.documentElement.scrollWidth > innerWidth+1"
                        )
                        results.append(
                            {
                                "device": device,
                                "scanner_report_routing": "passed",
                                "protected_excel": "passed",
                                "kite_reauthentication": "passed",
                                "paper_state": "unchanged",
                                "overflow": False,
                            }
                        )
                        context.close()
                    browser.close()
            finally:
                server.terminate()
                server.wait(timeout=20)
    (args.output_dir / "checks.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({"status": "passed", "checks": results}))


if __name__ == "__main__":
    main()
