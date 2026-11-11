"""Verify the deployed mobile paper URL without owner credentials or activation."""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    url = "https://trendforge-core.onrender.com/app/paper_session"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(
            viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
        )
        page.set_default_timeout(90000)
        response = page.goto(url, wait_until="domcontentloaded", timeout=90000)
        assert response is not None and response.status == 200
        page.get_by_label("Webapp access key", exact=True).wait_for()
        assert page.locator('input[type="password"]').count() == 1
        assert page.get_by_role(
            "button", name="Open TrendForge", exact=True
        ).is_visible()
        assert page.get_by_text("Connection error", exact=True).count() == 0
        assert page.url.rstrip("/") == url
        page.screenshot(
            path=str(args.output_dir / "public-mobile-signin.png"), full_page=True
        )
        browser.close()
    receipt = {
        "status": "passed",
        "url": url,
        "viewport": "390x844",
        "public_https": "passed",
        "owner_signin_required": True,
        "owner_credentials_used": False,
        "automation_activated": False,
        "broker_orders_submitted": 0,
        "scope": (
            "Public deployed mobile sign-in; authenticated controls tested "
            "separately with synthetic data"
        ),
    }
    (args.output_dir / "verification.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
