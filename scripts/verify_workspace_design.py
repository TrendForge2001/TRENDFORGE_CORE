"""Capture every page at laptop/mobile widths with synthetic data and owner auth."""

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

PAGES = (
    "watchlists",
    "technical_scanner",
    "kite_backtesting",
    "paper_session",
    "live_kite",
    "reports",
    "fundamental_scan",
    "institutional_scanner",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    checks = []
    with tempfile.TemporaryDirectory(prefix="tf-design-") as folder:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        key, admin = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            "PORT": str(port),
            "DATABASE_PATH": folder + "/book.db",
            "TRENDFORGE_DATA_DIR": folder,
            "TRENDFORGE_PRODUCTION_RUNTIME": "false",
            "TRENDFORGE_WEBAPP_ACCESS_KEY": key,
            "TRENDFORGE_ADMIN_API_KEY": admin,
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
            "TRENDFORGE_DESIGN_PREVIEW": "true",
        }
        with (args.output_dir / "server.txt").open("w") as log:
            process = subprocess.Popen(
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
                cwd=repo,
                env=env,
                stdout=log,
                stderr=log,
            )
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
                        ),
                        args=["--no-sandbox"],
                    )
                    base = f"http://127.0.0.1:{port}"
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
                        for _attempt in range(100):
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
                        page.goto(base + "/owner/" + device + "?next=/app/")
                        page.get_by_label("Webapp access key", exact=True).fill(key)
                        page.get_by_role(
                            "button", name="Open TrendForge", exact=True
                        ).click()
                        for name in PAGES:
                            page.goto(
                                base + "/app/" + ("" if name == "watchlists" else name)
                            )
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning"
                            )
                            expect(
                                page.get_by_label("Stock list", exact=True)
                            ).to_have_count(1)
                            expect(page.get_by_test_id("stException")).to_have_count(0)
                            if name == "watchlists":
                                page.get_by_role(
                                    "tab", name="Discover", exact=False
                                ).click()
                                expect(
                                    page.get_by_role("button", name="→", exact=True)
                                ).to_have_count(28)
                            if name == "technical_scanner":
                                expect(
                                    page.get_by_label("Research strategy", exact=True)
                                ).to_have_value(__import__("re").compile("Short Term"))
                                page.get_by_role(
                                    "button", name="Scan stocks", exact=True
                                ).click()
                                expect(
                                    page.get_by_text("Stocks & signals", exact=True)
                                ).to_be_visible(timeout=60000)
                            if name == "institutional_scanner":
                                page.get_by_role(
                                    "button",
                                    name="Fetch latest Big Shark data",
                                    exact=True,
                                ).click()
                                expect(
                                    page.get_by_text(
                                        "NSE disclosed trades — public report preview",
                                        exact=True,
                                    )
                                ).to_be_visible()
                            expect(page.get_by_test_id("stApp")).to_have_attribute(
                                "data-test-script-state", "notRunning"
                            )
                            overflow = page.evaluate(
                                "document.documentElement.scrollWidth > innerWidth + 1"
                            )
                            assert not overflow, (device, name, "horizontal overflow")
                            page.screenshot(
                                path=str(args.output_dir / f"{device}-{name}.png"),
                                full_page=True,
                            )
                            checks.append(
                                {
                                    "device": device,
                                    "page": name,
                                    "overflow": overflow,
                                    "exceptions": 0,
                                }
                            )
                            print(f"{device} {name}: passed", flush=True)
                        context.close()
                    browser.close()
            finally:
                process.terminate()
                process.wait(timeout=20)
    (args.output_dir / "checks.json").write_text(
        json.dumps({"synthetic_preview": True, "checks": checks}, indent=2)
    )


if __name__ == "__main__":
    main()
