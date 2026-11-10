"""Bounded, credential-free IP probes; never tests permission with an order."""

from __future__ import annotations

import ipaddress
from collections.abc import Callable
from contextlib import closing
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from providers.kite_egress import load_kite_egress

# Fixed TLS destinations only; no user-supplied probe URL or broker credential.
PROBE_URLS = (
    "https://api4.ipify.org",
    "https://checkip.amazonaws.com",
    "https://api4.ipify.org",
)


def kite_network_readiness(
    *, probe: bool = False, session_factory: Callable[[], Any] = requests.Session
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "status": "not_probed",
        "checked_at": datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
        "orders_submitted": 0,
        "broker_orders_allowed": False,
        "broker_whitelist_verified": False,
        "observed_ips": [],
        "expected_ips": [],
        "proxy_configured": False,
        "samples_completed": 0,
        "notes": "IP echo samples do not prove Kite order permission or future "
        "route stability. Confirm the provisioned IPs in the developer whitelist.",
    }
    try:
        configuration = load_kite_egress()
    except ValueError:
        return {**report, "status": "invalid_configuration"}
    report.update(configuration.public_configuration())
    if not configuration.proxy_url:
        return {**report, "status": "fixed_egress_not_configured"}
    if not probe:
        return report
    observed: set[str] = set()
    try:
        for url in PROBE_URLS:
            # Fresh sessions expose some rotation/failover mistakes and avoid
            # cookies or Authorization headers from any broker session.
            with (
                closing(session_factory()) as session,
                closing(
                    session.request(
                        "GET",
                        url,
                        headers={"Accept": "text/plain"},
                        timeout=(3, 5),
                        allow_redirects=False,
                        stream=True,
                        **configuration.request_options(),
                    )
                ) as response,
            ):
                if response.status_code != 200:
                    raise ValueError("IP probe unavailable")
                body = b""
                for chunk in response.iter_content(chunk_size=129):
                    body += chunk
                    if len(body) > 128:
                        raise ValueError("IP probe response is invalid")
                address = ipaddress.ip_address(body.decode("ascii").strip())
                if not address.is_global:
                    raise ValueError("IP probe response is invalid")
                observed.add(str(address))
                report["samples_completed"] += 1
    except (requests.RequestException, ValueError, UnicodeError, OSError):
        # Transport exceptions may embed proxy passwords. Never copy their text.
        report["status"] = "probe_unavailable"
    else:
        expected = set(configuration.expected_ips)
        report["status"] = (
            "expected_ips_missing"
            if not expected
            else "observed_ip_mismatch"
            if not observed.issubset(expected)
            else "observed_ips_match_configuration"
        )
    report["observed_ips"] = sorted(observed)
    return report
