"""Verify owner login, private upload and actual-flow signals on desktop and mobile."""

import argparse
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tf-institutional-ui-") as folder:
        root = Path(folder)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        key, admin = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            "PORT": str(port),
            "DATABASE_PATH": str(root / "book.db"),
            "TRENDFORGE_DATA_DIR": folder,
            "TRENDFORGE_PRODUCTION_RUNTIME": "false",
            "TRENDFORGE_WEBAPP_ACCESS_KEY": key,
            "TRENDFORGE_ADMIN_API_KEY": admin,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
        }
        # Only synthetic fixture data is ever written into browser evidence.
        subprocess.run(
            [
                args.runtime_python,
                "-c",
                "from openpyxl import Workbook\n"
                "from services.big_shark_portfolio import "
                "INVESTOR_HEADERS, STOCK_HEADERS, FLOW_HEADERS\n"
                "book=Workbook(); book.remove(book.active)\n"
                "for name,headers,rows in [\n"
                "('BIG SHARK', INVESTOR_HEADERS, []),\n"
                "('BIG SHARK STOCKS', STOCK_HEADERS, "
                "[['Example','Fund A','BOUGHT',0.05,0.001,100,123456]]),\n"
                "('TRADE FLOWS', FLOW_HEADERS, "
                "[['Example','Fund A',100,0,1200,0,'2026-01-01','2026-03-31']])]:\n"
                " sheet=book.create_sheet(name); sheet.append(headers)\n"
                " for row in rows: sheet.append(row)\n"
                "book.save(__import__('sys').argv[1])",
                str(root / "synthetic.xlsx"),
            ],
            cwd=repo,
            env=env,
            check=True,
        )
        with (args.output_dir / "server.txt").open("w") as log:
            process = subprocess.Popen(
                [
                    args.runtime_python,
                    "-m",
                    "uvicorn",
                    "tests.support.institutional_browser_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=repo,
                env=env,
                stdout=log,
                stderr=log,
            )
            base = f"http://127.0.0.1:{port}"
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(
                        **(
                            {
                                "executable_path": os.environ[
                                    "TRENDFORGE_BROWSER_EXECUTABLE"
                                ]
                            }
                            if os.getenv("TRENDFORGE_BROWSER_EXECUTABLE")
                            else {}
                        )
                    )
                    for mobile in (False, True):
                        context = browser.new_context(
                            viewport={"width": 390, "height": 844}
                            if mobile
                            else {"width": 1440, "height": 1000},
                            is_mobile=mobile,
                            has_touch=mobile,
                            accept_downloads=True,
                        )
                        page = context.new_page()
                        page.set_default_timeout(45000)
                        deadline = time.monotonic() + 40
                        while time.monotonic() < deadline:
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
                            page.request.get(base + "/institutional/big-shark").status
                            == 401
                        )
                        device = "mobile" if mobile else "laptop"
                        page.goto(
                            base
                            + "/owner/"
                            + device
                            + "?next=/app/institutional_scanner"
                        )
                        page.get_by_label("Webapp access key", exact=True).fill(key)
                        page.get_by_role(
                            "button", name="Open TrendForge", exact=True
                        ).click()
                        page.get_by_text(
                            "Institutional Scanner", exact=True
                        ).last.wait_for()
                        expect(
                            page.get_by_label("Big Shark stock selector", exact=True)
                        ).to_have_count(1)
                        page.get_by_text(
                            "Import / refresh private workbook", exact=True
                        ).click()
                        page.locator('input[type="file"]').first.set_input_files(
                            str(root / "synthetic.xlsx")
                        )
                        page.get_by_role(
                            "button", name="Import and recalculate", exact=True
                        ).click()
                        expect(
                            page.get_by_text(
                                "Private workbook imported and recalculated.",
                                exact=True,
                            )
                        ).to_be_visible()
                        expect(page.get_by_test_id("stApp")).to_have_attribute(
                            "data-test-script-state", "notRunning", timeout=30000
                        )
                        response = page.request.get(
                            base + "/institutional/big-shark",
                            headers={"X-TrendForge-Admin-Key": admin},
                        )
                        assert response.status == 200
                        assert response.json()["counts"] == {
                            "BUY": 1,
                            "SELL": 0,
                            "HOLD": 0,
                            "NO_DATA": 0,
                        }
                        assert response.json()["signals"][0]["avg_buy"] == 100
                        assert not response.json()["execution_enabled"]
                        page.get_by_text(
                            "Import actual trade disclosures (CSV)", exact=True
                        ).click()
                        page.get_by_text("Source quarter:", exact=False).wait_for()
                        csv_input = page.get_by_label(
                            "Actual trade CSV", exact=True
                        ).get_by_test_id("stFileUploaderDropzoneInput")
                        expect(csv_input).to_have_count(1)
                        csv_input.set_input_files(
                            {
                                "name": "synthetic-trades.csv",
                                "mimeType": "text/csv",
                                "buffer": (
                                    "Trade Date,Symbol,Stock Name,Investor "
                                    "Name,Side,Quantity,Price (₹)\n"
                                    "2026-01-05,EXAMPLE,Example,Fund A,BUY,100,20.50\n"
                                ).encode(),
                            }
                        )
                        expect(
                            page.get_by_text("synthetic-trades.csv", exact=True)
                        ).to_be_visible(timeout=30000)
                        page.get_by_role(
                            "button", name="Import trade disclosures", exact=True
                        ).click()
                        expect(
                            page.get_by_text(
                                "Trade disclosures imported: 1 matched records.",
                                exact=True,
                            )
                        ).to_be_visible(timeout=30000)
                        expect(page.get_by_test_id("stApp")).to_have_attribute(
                            "data-test-script-state", "notRunning", timeout=30000
                        )
                        page.get_by_text(
                            "Activity compares matched disclosed trades only.",
                            exact=False,
                        ).wait_for()
                        page.get_by_text(
                            "Check daily technical confirmation", exact=True
                        ).click()
                        expect(
                            page.get_by_label("Stock to confirm", exact=True)
                        ).to_be_visible()
                        page.get_by_role(
                            "button", name="Check daily confirmation", exact=True
                        ).click()
                        deadline = time.monotonic() + 45
                        while time.monotonic() < deadline:
                            payload = page.request.get(
                                base + "/institutional/big-shark",
                                headers={"X-TrendForge-Admin-Key": admin},
                            ).json()
                            signal = payload["signals"][0]
                            if signal["technical_confirmation"] != "NOT_CHECKED":
                                break
                            time.sleep(0.2)
                        assert signal["activity_signal"] == "BUY"
                        assert signal["technical_confirmation"] in {
                            "BUY_CONFIRMED",
                            "WAIT",
                        }, {
                            "evidence": signal["technical_evidence"],
                            "alerts": page.get_by_test_id(
                                "stAlert"
                            ).all_text_contents(),
                            "selection": page.get_by_label(
                                "Stock to confirm", exact=True
                            ).inner_text(),
                        }
                        assert signal["data_coverage"] == "DISCLOSED_ONLY"
                        assert signal["disclosure_time"] is None
                        assert signal["technical_checked_at"]
                        assert (
                            page.request.get(
                                base + "/institutional/big-shark/workbook"
                            ).status
                            == 401
                        )
                        page.get_by_role(
                            "button", name="Prepare refreshed workbook", exact=True
                        ).click()
                        expect(page.get_by_test_id("stApp")).to_have_attribute(
                            "data-test-script-state", "notRunning", timeout=30000
                        )
                        # A separate control reruns the page. Prepared exports
                        # must survive it while the snapshot remains unchanged.
                        page.get_by_role(
                            "button", name="Prepare trade CSV template", exact=True
                        ).click()
                        expect(page.get_by_test_id("stApp")).to_have_attribute(
                            "data-test-script-state", "notRunning", timeout=30000
                        )
                        with page.expect_download() as download:
                            page.get_by_role(
                                "button",
                                name="Download recalculated sheets",
                                exact=True,
                            ).click()
                        download.value.save_as(
                            args.output_dir / (device + "-synthetic.xlsx")
                        )
                        page.screenshot(
                            path=str(args.output_dir / (device + "-institutional.png")),
                            full_page=True,
                        )
                        page.goto(base + "/owner/logout")
                        expect(
                            page.get_by_label("Webapp access key", exact=True)
                        ).to_be_visible()
                        assert context.cookies() and not any(
                            c["name"] == "tf_owner_session" for c in context.cookies()
                        )
                        context.close()
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=20)
    print(
        "Verified desktop/mobile owner login, private workbook/CSV imports, "
        "activity evidence, daily confirmation, export and logout."
    )


if __name__ == "__main__":
    main()
