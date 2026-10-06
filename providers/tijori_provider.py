"""Configurable Tijori fundamental-data adapter.

Tijori's public developer API is limited; enterprise/custom customers receive
provider-specific endpoint details. TrendForge therefore accepts the exact
fundamentals URL template and authentication details via environment/config
instead of hard-coding an undocumented endpoint.
"""
from __future__ import annotations

from typing import Any, Mapping
import os

import requests

from providers.fundamental_mapping import build_snapshot, extract_fields, parse_field_map


class TijoriFundamentalProvider:
    NAME = "TijoriFundamentalProvider"

    def __init__(
        self,
        *,
        url_template: str | None = None,
        api_key: str | None = None,
        api_key_header: str | None = None,
        api_key_prefix: str | None = None,
        field_map: str | Mapping[str, Any] | None = None,
        timeout_seconds: float | None = None,
        session: Any | None = None,
    ) -> None:
        self.url_template = (
            url_template
            if url_template is not None
            else os.getenv("TIJORI_FUNDAMENTALS_URL_TEMPLATE")
        )
        self.api_key = api_key if api_key is not None else os.getenv("TIJORI_API_KEY")
        self.api_key_header = (
            api_key_header
            if api_key_header is not None
            else os.getenv("TIJORI_API_KEY_HEADER", "Authorization")
        )
        self.api_key_prefix = (
            api_key_prefix
            if api_key_prefix is not None
            else os.getenv("TIJORI_API_KEY_PREFIX", "Bearer")
        )
        raw_map = field_map if field_map is not None else os.getenv("TIJORI_FIELD_MAP_JSON")
        self.field_map = parse_field_map(raw_map)
        raw_timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else os.getenv("TIJORI_TIMEOUT_SECONDS", "10")
        )
        self.timeout_seconds = max(1.0, float(raw_timeout))
        self.session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.url_template and "{symbol}" in self.url_template)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.api_key:
            value = self.api_key
            if self.api_key_prefix:
                value = f"{self.api_key_prefix.strip()} {value}"
            headers[self.api_key_header or "Authorization"] = value
        return headers

    @staticmethod
    def _payload(response: Any) -> Mapping[str, Any]:
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise ValueError("Tijori fundamentals response must be a JSON object")
        # Permit common envelope keys without assuming one is mandatory.
        for key in ("data", "result", "company", "fundamentals"):
            nested = payload.get(key)
            if isinstance(nested, Mapping):
                return nested
        return payload

    def get(self, symbol: str, payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        symbol = str(symbol or "").strip().upper()
        if not symbol:
            raise ValueError("Symbol is required for Tijori fundamentals")
        if not self.configured:
            return None

        url = self.url_template.format(symbol=symbol)
        response = self.session.get(
            url,
            headers=self._headers(),
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = self._payload(response)
        values = extract_fields(raw, self.field_map)

        as_of = None
        for key in ("as_of", "asOf", "updated_at", "updatedAt", "date"):
            value = raw.get(key)
            if value:
                as_of = str(value)
                break

        return build_snapshot(
            provider=self.NAME,
            symbol=symbol,
            values=values,
            as_of=as_of,
            extra_meta={"source": "tijori_custom_api"},
        )

    def get_fundamentals(self, symbol: str) -> dict[str, Any] | None:
        return self.get(symbol)

    def health(self) -> dict[str, Any]:
        return {
            "status": "configured" if self.configured else "not_configured",
            "provider": self.NAME,
            "network_probe": False,
            "url_template_configured": bool(self.url_template),
            "url_has_symbol_placeholder": bool(
                self.url_template and "{symbol}" in self.url_template
            ),
            "api_key_configured": bool(self.api_key),
        }


__all__ = ["TijoriFundamentalProvider"]
