"""Read-only PC Kite diagnosis; never prints keys, tokens or account data."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import dotenv_values

from core.pc_kite_credentials import FIELDS, load_pc_kite_credentials
from providers.kite_diagnostics import MESSAGES, session_failure
from providers.kite_rest_client import KiteRESTClient


def diagnose(root: Path, *, client_factory=KiteRESTClient) -> dict:
    path = root / "private" / "kite.env"
    report = {
        "credential_file_found": path.is_file(),
        "possible_txt_extension": path.with_suffix(".env.txt").is_file(),
        "credentials_loaded": {},
        "profile_authenticated": False,
        "quotes_available": False,
    }
    try:
        # Same precedence as the launcher: private file, process env, repo .env.
        fallback = dotenv_values(
            Path(__file__).resolve().parents[1] / ".env",
            encoding="utf-8-sig",
            interpolate=False,
        )
        values = {
            name: os.environ.get(name) or fallback.get(name) or "" for name in FIELDS
        }
        values.update(load_pc_kite_credentials(root))
        values = {name: str(values[name]).strip() for name in FIELDS}
    except (OSError, ValueError, UnicodeError):
        return {**report, "status": "credential_file_unreadable"}
    report["credentials_loaded"] = {name: bool(values[name]) for name in FIELDS}
    missing = (
        "api_key_missing"
        if not values["KITE_API_KEY"]
        else "access_token_missing"
        if not values["KITE_ACCESS_TOKEN"]
        else None
    )
    if missing:
        return {
            **report,
            "status": "configuration_required",
            "diagnostic": {"code": missing, "message": MESSAGES[missing]},
        }
    client = client_factory(
        api_key=values["KITE_API_KEY"], access_token=values["KITE_ACCESS_TOKEN"]
    )
    try:
        profile = client.profile()
        if not isinstance(profile, dict):
            raise ValueError("Invalid profile response")
        report["profile_authenticated"] = True
        quotes = client.quote(["NSE:RELIANCE"])
        report["quotes_available"] = isinstance(quotes, dict) and isinstance(
            quotes.get("NSE:RELIANCE"), dict
        )
        report["status"] = (
            "ready" if report["quotes_available"] else "quote_unavailable"
        )
    except Exception as error:
        report["status"] = (
            "quote_unavailable"
            if report["profile_authenticated"]
            else "session_unavailable"
        )
        report["diagnostic"] = session_failure(error)
    return report


def main(argv: list[str] | None = None) -> int:
    default_root = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        / "TrendForgeCore"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=default_root)
    args = parser.parse_args(argv)
    report = diagnose(args.data_dir)
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
