"""Operator-configured CONNECT routing, scoped to Kite REST requests."""

from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import unquote, urlsplit

PROXY_ENV = "TRENDFORGE_KITE_PROXY_URL"
IPS_ENV = "TRENDFORGE_KITE_EGRESS_IPS"


@dataclass(frozen=True)
class KiteEgress:
    # A proxy URL can contain a password. Never include it in repr or reports.
    proxy_url: str = field(default="", repr=False)
    expected_ips: tuple[str, ...] = ()

    def request_options(self) -> dict[str, Any]:
        if not self.proxy_url:
            return {}
        # Per-request proxies override inherited HTTPS_PROXY/NO_PROXY settings.
        # A failed configured route must never fall back to a direct connection.
        return {"proxies": {"https": self.proxy_url}, "verify": True}

    def public_configuration(self) -> dict[str, Any]:
        return {
            "proxy_configured": bool(self.proxy_url),
            "expected_ips": list(self.expected_ips),
            "broker_whitelist_verified": False,
            "orders_submitted": 0,
        }


def load_kite_egress(environ: Mapping[str, str] | None = None) -> KiteEgress:
    env = os.environ if environ is None else environ
    proxy = str(env.get(PROXY_ENV) or "").strip()
    raw_ips = str(env.get(IPS_ENV) or "").strip()
    if proxy:
        try:
            parsed = urlsplit(proxy)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or any(c.isspace() or ord(c) < 32 for c in unquote(proxy))
            ):
                raise ValueError
            # Evaluating port also rejects malformed and out-of-range values.
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError
        except (ValueError, UnicodeError):
            raise ValueError("Kite proxy configuration is invalid") from None
    ips: list[str] = []
    try:
        for item in raw_ips.replace(",", " ").split():
            address = ipaddress.ip_address(item)
            if not address.is_global:
                raise ValueError
            canonical = str(address)
            if canonical not in ips:
                ips.append(canonical)
        if len(ips) > 2:
            raise ValueError
    except ValueError:
        raise ValueError("Configure at most two public Kite egress IPs") from None
    return KiteEgress(proxy, tuple(ips))
