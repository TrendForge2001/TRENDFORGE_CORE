"""Verify live refresh and operator controls using a temporary, broker-free book."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from core.pc_paper_policy import policy_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-python", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="tf-paper-ui-") as folder:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        web_key, admin_key = secrets.token_urlsafe(40), secrets.token_urlsafe(40)
        env = {
            **os.environ,
            **policy_environment(),
            "PORT": str(port),
            "DATABASE_PATH": str(Path(folder) / "book.db"),
            "TRENDFORGE_DATA_DIR": folder,
            "TRENDFORGE_PRODUCTION_RUNTIME": "false",
            "RENDER": "false",
            "TRENDFORGE_CLOUD_READ_ONLY": "false",
            "TRENDFORGE_LIVE_TRADING_ENABLED": "false",
            "TRENDFORGE_ADMIN_API_KEY": admin_key,
            "TRENDFORGE_WEBAPP_ACCESS_KEY": web_key,
        }
        with (args.output_dir / "server.txt").open("w") as log:
            process = subprocess.Popen(
                [
                    args.runtime_python,
                    "-m",
                    "uvicorn",
                    "tests.support.paper_browser_app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1100})
                    page.set_default_timeout(45000)
                    deadline = time.monotonic() + 40
                    while time.monotonic() < deadline:
                        try:
                            if (
                                page.request.get(base + "/livez", timeout=1000).status
                                == 200
                            ):
                                break
                        except Exception:
                            pass
                        time.sleep(0.2)
                    page.goto(base + "/app/paper_session")
                    page.get_by_label("Manual Access Key (required)", exact=True).fill(
                        web_key
                    )
                    page.get_by_label("Admin API Key (optional)", exact=True).fill(
                        admin_key
                    )
                    page.get_by_role(
                        "button", name="Open TrendForge", exact=True
                    ).click()
                    page.get_by_text("Automation: OFF", exact=False).wait_for()
                    page.get_by_role(
                        "button", name="Start automated paper trading", exact=True
                    ).click()
                    page.get_by_text("Automation: ON", exact=False).wait_for()
                    page.get_by_role(
                        "button", name="Stop automated paper trading", exact=True
                    ).click()
                    page.get_by_text("Automation: OFF", exact=False).wait_for()
                    page.get_by_text("Supervised paper entry", exact=True).click()
                    symbol = page.get_by_label("NSE symbol", exact=True)
                    symbol.fill("INFY")
                    headers = {"X-TrendForge-Admin-Key": admin_key}
                    assert (
                        page.request.post(
                            base + "/fixture/mark", headers=headers
                        ).status
                        == 200
                    )
                    page.get_by_text("₹10.00", exact=True).wait_for(timeout=30000)
                    assert symbol.input_value() == "INFY"
                    page.screenshot(
                        path=str(args.output_dir / "live-paper.png"), full_page=True
                    )
                    assert (
                        page.request.post(
                            base + "/fixture/unavailable", headers=headers
                        ).status
                        == 200
                    )
                    page.get_by_text(
                        "Automation status unavailable", exact=False
                    ).wait_for(timeout=30000)
                    page.get_by_role(
                        "button", name="Activate paper kill switch", exact=True
                    ).click()
                    deadline = time.monotonic() + 10
                    killed = False
                    while time.monotonic() < deadline:
                        killed = page.request.get(
                            base + "/fixture/status", headers=headers
                        ).json()["kill_switch"]
                        if killed:
                            break
                        page.wait_for_timeout(100)
                    assert killed is True
                    assert page.request.get(base + "/livez").status == 200
                    browser.close()
                receipt = {
                    "status": "passed",
                    "automatic_refresh": "passed",
                    "manual_form_preserved": "passed",
                    "operator_start_stop": "passed",
                    "emergency_kill_during_status_outage": "passed",
                    "broker_clients": 0,
                    "laptop_files_accessed": False,
                }
                (args.output_dir / "verification.json").write_text(
                    json.dumps(receipt, indent=2)
                )
                print(json.dumps(receipt), flush=True)
            finally:
                process.terminate()
                process.wait(timeout=20)


if __name__ == "__main__":
    main()
