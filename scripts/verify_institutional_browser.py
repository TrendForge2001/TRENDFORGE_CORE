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
    parser.add_argument("--holdings-unavailable", action="store_true")
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
            "TRENDFORGE_OWNER_SIGNING_SECRET": secrets.token_urlsafe(40),
            "TRENDFORGE_WEBAPP_ACCESS_KEY": key,
            "TRENDFORGE_ADMIN_API_KEY": admin,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_TEST_HOLDINGS_UNAVAILABLE": str(
                args.holdings_unavailable
            ).lower(),
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

                        def settled(page=page):
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning", timeout=30000
                            )
                            page.evaluate(
                                "() => new Promise(resolve => "
                                "requestAnimationFrame(() => "
                                "requestAnimationFrame(resolve)))"
                            )

                        def tab(name, page=page, settled=settled):
                            page.get_by_role("tab", name=name, exact=True).click()
                            settled()

                        def data(path, page=page):
                            return page.request.get(
                                base + path, headers={"X-TrendForge-Admin-Key": admin}
                            ).json()

                        def upload(label, payload, page=page, settled=settled):
                            with page.expect_response(
                                lambda response: (
                                    "/_stcore/upload_file/" in response.url
                                    and response.request.method == "PUT"
                                )
                            ) as receipt:
                                page.get_by_label(label, exact=True).get_by_test_id(
                                    "stFileUploaderDropzoneInput"
                                ).set_input_files(payload)
                            assert receipt.value.status == 204
                            expect(page.get_by_role("progressbar")).to_have_count(0)
                            settled()

                        page.get_by_text(
                            "Institutional Data", exact=True
                        ).last.wait_for()
                        settled()
                        # A cold server must fetch actual disclosures independently
                        # even when the holdings site refuses access.
                        previous = data("/institutional/big-shark/sources").get(
                            "checked_at"
                        )
                        page.get_by_role(
                            "button", name="Fetch latest Big Shark data", exact=True
                        ).click()
                        deadline = time.monotonic() + 45
                        while time.monotonic() < deadline:
                            public = data("/institutional/big-shark/sources")
                            if (
                                public.get("checked_at") != previous
                                and public.get("trades", {}).get("records_received")
                                == 2
                            ):
                                break
                            time.sleep(0.2)
                        else:
                            raise AssertionError(
                                "Independent NSE disclosure refresh did not complete"
                            )
                        if args.holdings_unavailable:
                            assert public["failures"] == {
                                "MONEYCONTROL": "SOURCE_ACCESS_UNAVAILABLE"
                            }
                            if not mobile:
                                assert public["portfolio_loaded"] is False
                                assert (
                                    page.request.get(
                                        base + "/institutional/big-shark",
                                        headers={"X-TrendForge-Admin-Key": admin},
                                    ).status
                                    == 404
                                )
                        expect(
                            page.get_by_text(
                                "NSE disclosed trades — public report preview",
                                exact=True,
                            )
                        ).to_be_visible()
                        tab("Private imports")
                        upload("Big Shark workbook", str(root / "synthetic.xlsx"))
                        page.get_by_role(
                            "button", name="Import and recalculate", exact=True
                        ).click()
                        expect(
                            page.get_by_text(
                                "Private workbook imported and recalculated.",
                                exact=True,
                            )
                        ).to_be_visible()
                        settled()
                        snapshot = data("/institutional/big-shark")
                        assert snapshot["signals"][0]["avg_buy"] == 100
                        assert snapshot["execution_enabled"] is False
                        page.get_by_text(
                            "Import actual trade disclosures (CSV)", exact=True
                        ).click()
                        upload(
                            "Actual trade CSV",
                            {
                                "name": "synthetic-trades.csv",
                                "mimeType": "text/csv",
                                "buffer": (
                                    b"Trade Date,Symbol,Stock Name,Investor Name,"
                                    b"Side,Quantity,Price\n"
                                    b"2026-01-05,EXAMPLE,Example,Fund A,BUY,100,20.50\n"
                                ),
                            },
                        )
                        page.get_by_role(
                            "button", name="Import trade disclosures", exact=True
                        ).click()
                        expect(
                            page.get_by_text(
                                "Trade disclosures imported: 1 matched records.",
                                exact=True,
                            )
                        ).to_have_count(1)
                        settled()
                        tab("Activity & ratings")
                        page.get_by_text(
                            "Check daily technical confirmation", exact=True
                        ).click()
                        picker = page.get_by_label("Stock to confirm", exact=True)
                        expect(picker).to_have_value("EXAMPLE")
                        settled()
                        page.get_by_role(
                            "button", name="Check daily confirmation", exact=True
                        ).click()
                        deadline = time.monotonic() + 45
                        while time.monotonic() < deadline:
                            signal = data("/institutional/big-shark")["signals"][0]
                            if signal["technical_confirmation"] != "NOT_CHECKED":
                                break
                            time.sleep(0.2)
                        assert signal["activity_signal"] == "BUY"
                        assert signal["technical_confirmation"] in {
                            "WAIT",
                            "STALE_DATA",
                        }
                        assert signal["disclosure_time"] is None
                        settled()
                        page.get_by_role(
                            "button", name="Prepare refreshed workbook", exact=True
                        ).click()
                        workbook_download = page.get_by_role(
                            "button", name="Download recalculated sheets", exact=True
                        )
                        expect(workbook_download).to_be_visible()
                        settled()
                        tab("Private imports")
                        page.get_by_text(
                            "Import actual trade disclosures (CSV)", exact=True
                        ).click()
                        page.get_by_role(
                            "button", name="Prepare trade CSV template", exact=True
                        ).click()
                        expect(
                            page.get_by_role(
                                "button", name="Download trade CSV template", exact=True
                            )
                        ).to_be_visible()
                        tab("Activity & ratings")
                        expect(workbook_download).to_be_visible()
                        with page.expect_download() as download:
                            workbook_download.click()
                        download.value.save_as(
                            args.output_dir / (device + "-synthetic.xlsx")
                        )
                        tab("Public feeds")
                        schedule = page.get_by_label(
                            "Refresh public feeds daily, even when this page is closed",
                            exact=True,
                        )
                        if not schedule.is_checked():
                            page.get_by_text(
                                "Refresh public feeds daily, even when this "
                                "page is closed",
                                exact=True,
                            ).click()
                        previous = data("/institutional/big-shark/sources").get(
                            "checked_at"
                        )
                        page.get_by_role(
                            "button", name="Fetch latest Big Shark data", exact=True
                        ).click()
                        deadline = time.monotonic() + 45
                        while time.monotonic() < deadline:
                            public = data("/institutional/big-shark/sources")
                            actual = data("/institutional/big-shark")
                            if (
                                public.get("checked_at") != previous
                                and public.get("config", {}).get("enabled") is True
                                and actual.get("snapshot_id")
                                == public.get("snapshot_id")
                            ):
                                break
                            time.sleep(0.2)
                        else:
                            raise AssertionError(
                                "Public source schedule receipt did not reconcile"
                            )
                        assert actual["signals"][0]["activity_signal"] == "SELL"
                        assert actual["signals"][0]["avg_buy"] == 12
                        assert actual["signals"][0]["avg_sell"] == 30
                        assert actual["execution_enabled"] is False
                        settled()
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
        "activity evidence, daily confirmation, public-source refresh, "
        "daily schedule controls, export and logout."
    )


if __name__ == "__main__":
    main()
