"""Verify reference-style stock cards and exports with synthetic data only."""

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(exist_ok=True, parents=True)
    root = Path(__file__).resolve().parents[1]
    results = []
    with tempfile.TemporaryDirectory(prefix="tf-report-") as folder:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        access, admin = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            "PORT": str(port),
            "DATABASE_PATH": folder + "/book.db",
            "TRENDFORGE_DATA_DIR": folder,
            "TRENDFORGE_PRODUCTION_RUNTIME": "false",
            "TRENDFORGE_WEBAPP_ACCESS_KEY": access,
            "TRENDFORGE_ADMIN_API_KEY": admin,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
        }
        with (args.output_dir / "server.txt").open("w") as log:
            process = subprocess.Popen(
                [
                    args.runtime_python,
                    "-m",
                    "uvicorn",
                    "tests.support.stock_report_browser_app:app",
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
                    base = f"http://127.0.0.1:{port}"
                    for device, width, height in [
                        ("laptop", 1440, 1000),
                        ("mobile", 390, 844),
                    ]:
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            is_mobile=device == "mobile",
                            has_touch=device == "mobile",
                            accept_downloads=True,
                        )
                        page = context.new_page()
                        page.set_default_timeout(30000)
                        try:
                            for _ in range(100):
                                if process.poll() is not None:
                                    raise AssertionError(
                                        "Synthetic report server stopped"
                                    )
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
                                page.request.get(
                                    base + "/reports/stocks/EXAMPLE"
                                ).status
                                == 401
                            )
                            page.goto(
                                base
                                + "/owner/"
                                + device
                                + "?next=/app/technical_scanner"
                            )
                            page.get_by_label("Webapp access key", exact=True).fill(
                                access
                            )
                            page.get_by_role(
                                "button", name="Open TrendForge", exact=True
                            ).click()
                            page.get_by_role(
                                "tab", name="Stock report", exact=True
                            ).click()
                            page.get_by_label("NSE stock symbol", exact=True).fill(
                                "EXAMPLE"
                            )
                            page.get_by_role(
                                "button", name="Generate stock report", exact=True
                            ).click()
                            expect(
                                page.get_by_text(
                                    "Example Telecom Ltd · synthetic preview",
                                    exact=True,
                                )
                            ).to_be_visible()
                            expect(page.get_by_test_id("stException")).to_have_count(0)
                            expect(
                                page.get_by_role(
                                    "button", name="Review paper trade", exact=True
                                )
                            ).to_be_enabled()
                            # A short-term EMA setup uses its indicator trail,
                            # rather than fabricated annual profit targets.
                            expect(
                                page.get_by_text(
                                    (
                                        "Use the approved EMA20 profit trail; there i"
                                        "s no fixed numeric take-profit target."
                                    ),
                                    exact=True,
                                )
                            ).to_have_count(1)
                            page.get_by_text("Long Term", exact=True).last.click()
                            # Changing the horizon clears the previous report on
                            # the server. Wait for that rerun before generating,
                            # rather than clicking the previous render's button.
                            expect(
                                page.locator(".st-key-tf_stock_report_body")
                            ).to_have_count(0)
                            page.get_by_role(
                                "button", name="Generate stock report", exact=True
                            ).click()
                            expect(
                                page.get_by_text(
                                    "Example Telecom Ltd · synthetic preview",
                                    exact=True,
                                )
                            ).to_be_visible()
                            expect(page.locator(".tf-r-hero")).to_contain_text(
                                "Long-Term EMA 100/200"
                            )
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning"
                            )
                            expect(
                                page.get_by_text("Financials", exact=False).first
                            ).to_be_visible()
                            page.get_by_text(
                                "Example Telecom Ltd · synthetic preview", exact=True
                            ).scroll_into_view_if_needed()
                            page.screenshot(
                                path=str(args.output_dir / (device + "-hero.png")),
                                full_page=True,
                            )
                            for label in ("Net profit", "Quarterly", "Past volume"):
                                control = page.get_by_text(label, exact=True)
                                # Click retries across Streamlit's DOM replacement
                                # and scrolls automatically when the control settles.
                                control.click()
                                expect(page.get_by_test_id("stApp")).to_have_attribute(
                                    "data-test-script-state", "notRunning"
                                )
                                page.evaluate(
                                    "() => new Promise(resolve => requestAnimatio"
                                    "nFrame(() => requestAnimationFrame(resolve))"
                                    ")"
                                )
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning"
                            )
                            expect(
                                page.get_by_test_id("stVegaLiteChart")
                            ).to_have_count(4)
                            page.wait_for_function(
                                "() => [...document.querySelectorAll('[data-t"
                                "estid=stVegaLiteChart]')].every(el => [...el"
                                ".querySelectorAll('svg, canvas')].some(chart"
                                " => chart.getBoundingClientRect().height > 1"
                                "00))"
                            )
                            assert not page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth+1"
                            )
                            page.get_by_text(
                                "Overview", exact=True
                            ).scroll_into_view_if_needed()
                            page.screenshot(
                                path=str(args.output_dir / (device + "-overview.png")),
                                full_page=True,
                            )
                            page.get_by_text(
                                "⚡ Fundamentals", exact=True
                            ).scroll_into_view_if_needed()
                            page.screenshot(
                                path=str(
                                    args.output_dir / (device + "-fundamentals.png")
                                ),
                                full_page=True,
                            )
                            page.get_by_text(
                                "▥ Financials", exact=True
                            ).scroll_into_view_if_needed()
                            page.screenshot(
                                path=str(
                                    args.output_dir / (device + "-financials.png")
                                ),
                                full_page=True,
                            )
                            with page.expect_download() as receipt:
                                page.get_by_role(
                                    "button", name="Save report", exact=True
                                ).click()
                            path = args.output_dir / (device + "-EXAMPLE-report.html")
                            receipt.value.save_as(path)
                            assert "synthetic preview" in path.read_text()
                            assert "<script" not in path.read_text().lower()
                            if device == "laptop":
                                export = context.new_page()
                                export.set_content(path.read_text(), wait_until="load")
                                export.pdf(
                                    path=str(
                                        args.output_dir / "EXAMPLE-Synthetic-Report.pdf"
                                    ),
                                    format="A4",
                                    print_background=True,
                                )
                                export.close()
                            before = page.request.get(
                                base + "/fixture/status",
                                headers={"X-TrendForge-Admin-Key": admin},
                            ).json()
                            assert before["automation_enabled"] is False
                            page.get_by_role(
                                "button", name="Review paper trade", exact=True
                            ).click()
                            expect(
                                page.get_by_text(
                                    "Reviewing EXAMPLE from its research report.",
                                    exact=False,
                                )
                            ).to_be_visible()
                            after = page.request.get(
                                base + "/fixture/status",
                                headers={"X-TrendForge-Admin-Key": admin},
                            ).json()
                            assert after == before
                            results.append(
                                {
                                    "device": device,
                                    "overflow": False,
                                    "report_controls": "passed",
                                    "export": "passed",
                                    "paper_review": "navigation; automation unchanged",
                                }
                            )
                            context.close()
                        except Exception:
                            page.screenshot(
                                path=str(args.output_dir / "failure.png"),
                                full_page=True,
                            )
                            (args.output_dir / "failure-dom.txt").write_text(
                                page.locator("body").inner_text()
                            )
                            raise

                    probe = browser.new_context()
                    response = probe.request.post(
                        base + "/fixture/reports/use-real-scanner",
                        headers={"X-TrendForge-Admin-Key": admin},
                    )
                    assert response.status == 200
                    assert response.json()["real_scan_engine"] is True
                    probe.close()
                    for device, width, height in [
                        ("laptop", 1440, 1000),
                        ("mobile", 390, 844),
                    ]:
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            is_mobile=device == "mobile",
                            has_touch=device == "mobile",
                        )
                        page = context.new_page()
                        page.set_default_timeout(30000)
                        page.goto(
                            base + "/owner/" + device + "?next=/app/technical_scanner"
                        )
                        page.get_by_label("Webapp access key", exact=True).fill(access)
                        page.get_by_role(
                            "button", name="Open TrendForge", exact=True
                        ).click()
                        page.get_by_role("tab", name="Stock report", exact=True).click()
                        page.get_by_label("NSE stock symbol", exact=True).fill(
                            "EXAMPLE"
                        )
                        for horizon in ("Short Term", "Long Term"):
                            if horizon == "Long Term":
                                page.get_by_text("Long Term", exact=True).last.click()
                                expect(
                                    page.locator(".st-key-tf_stock_report_body")
                                ).to_have_count(0)
                            page.get_by_role(
                                "button", name="Generate stock report", exact=True
                            ).click()
                            condition = page.request.get(
                                base + "/reports/stocks/EXAMPLE",
                                headers={"X-TrendForge-Admin-Key": admin},
                                params={
                                    "horizon": "long_term"
                                    if horizon == "Long Term"
                                    else "short_term"
                                },
                            ).json()["conditional_plan"]
                            assert (
                                condition["stop_reference"]
                                < condition["entry"]
                                < condition["targets"][0]
                            )
                            assert condition["execution_enabled"] is False
                            expect(page.locator(".tf-r-hero")).to_contain_text("/60")
                            expect(page.locator(".tf-r-hero")).to_contain_text(
                                "No matched actual institutional trade data "
                                "for this stock"
                            )
                            expect(
                                page.locator("summary").filter(
                                    has_text="Entry conditions ·"
                                )
                            ).to_have_count(1)
                            expect(page.get_by_test_id("stException")).to_have_count(0)
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning"
                            )
                            assert not page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth+1"
                            )
                        page.locator(".tf-r-hero").evaluate(
                            "el => el.scrollIntoView({block: 'start'})"
                        )
                        page.screenshot(
                            path=str(args.output_dir / (device + "-real-scanner.png"))
                        )
                        results.append(
                            {
                                "device": device + "-real-scanner",
                                "horizons": ["short_term", "long_term"],
                                "technical_component": "available",
                                "institutional_data": "missing reason shown",
                                "entry_conditions": "shown",
                                "overflow": False,
                            }
                        )
                        context.close()
                    for device, width, height in [
                        ("laptop", 1440, 1000),
                        ("mobile", 390, 844),
                    ]:
                        context = browser.new_context(
                            viewport={"width": width, "height": height},
                            is_mobile=device == "mobile",
                            accept_downloads=True,
                        )
                        page = context.new_page()
                        page.set_default_timeout(30000)
                        headers = {"X-TrendForge-Admin-Key": admin}
                        assert (
                            page.request.post(
                                base + "/fixture/paper/close", headers=headers
                            ).status
                            == 200
                        )
                        before = page.request.get(
                            base + "/fixture/status", headers=headers
                        ).json()
                        page.goto(
                            base + "/owner/" + device + "?next=/app/paper_session"
                        )
                        page.get_by_label("Webapp access key", exact=True).fill(access)
                        page.get_by_role(
                            "button", name="Open TrendForge", exact=True
                        ).click()
                        page.get_by_text("Trade reports", exact=True).click()
                        expect(
                            page.get_by_label("Trade report period", exact=True)
                        ).to_have_value("All time")
                        report = page.request.get(
                            base + "/paper/trade-reports?period=all", headers=headers
                        ).json()
                        assert report["summary"]["closed_fills"] == 1
                        expect(page.get_by_test_id("stDataFrame").first).to_be_visible()
                        page.get_by_text(
                            "Trade explanation & P&L reconciliation", exact=True
                        ).click()
                        expect(
                            page.get_by_label("Inspect closed fill", exact=True)
                        ).to_be_visible()
                        expect(
                            page.get_by_text(
                                "The observed quote reached the recorded "
                                "profit target.",
                                exact=True,
                            )
                        ).to_be_visible()
                        expect(
                            page.get_by_text(
                                "Historical evidence is incomplete; full "
                                "reconciliation cannot be claimed.",
                                exact=True,
                            )
                        ).to_be_visible()
                        with page.expect_download() as receipt:
                            page.get_by_role(
                                "link",
                                name="Download paper trade report (.xlsx)",
                                exact=True,
                            ).click()
                        path = args.output_dir / (device + "-paper-history.xlsx")
                        receipt.value.save_as(path)
                        assert not path.read_bytes().startswith(b"PK")
                        checked = subprocess.run(
                            [
                                args.runtime_python,
                                "-c",
                                "import io,os,sys,msoffcrypto,openpyxl;"
                                "f=msoffcrypto.OfficeFile(io.BytesIO(sys.stdin.buffer.read()));"
                                "f.load_key(password=os.environ['TRENDFORGE_VERIFY_PASSWORD']);"
                                "o=io.BytesIO();f.decrypt(o);w=openpyxl.load_workbook(o,read_only=True);"
                                "r=list(w['Closed paper trades'].values);"
                                "assert len(r)==2 and len(r[0])==13;"
                                "assert r[1][2]==100 and r[1][3]==110;"
                                "a=list(w['P&L reconciliation'].values);"
                                "assert len(a)==2 and 'status' in a[0] "
                                "and 'strategy.registry_version' in a[0];"
                                "print('protected_history_verified')",
                            ],
                            input=path.read_bytes(),
                            env={**os.environ, "TRENDFORGE_VERIFY_PASSWORD": access},
                            capture_output=True,
                            check=True,
                        )
                        assert b"protected_history_verified" in checked.stdout
                        assert (
                            page.request.get(
                                base + "/fixture/status", headers=headers
                            ).json()
                            == before
                        )
                        expect(page.get_by_test_id("stException")).to_have_count(0)
                        assert not page.evaluate(
                            "document.documentElement.scrollWidth > innerWidth+1"
                        )
                        page.screenshot(
                            path=str(args.output_dir / (device + "-paper-history.png")),
                            full_page=True,
                        )
                        results.append(
                            {
                                "device": device + "-paper-history",
                                "closed_fill_visible": True,
                                "default_period": "all",
                                "encrypted_export": "passed",
                                "columns": 12,
                            }
                        )
                        context.close()
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=20)
    (args.output_dir / "checks.json").write_text(
        json.dumps({"synthetic": True, "checks": results}, indent=2)
    )
    print(json.dumps({"status": "passed", "devices": results}))


if __name__ == "__main__":
    main()
