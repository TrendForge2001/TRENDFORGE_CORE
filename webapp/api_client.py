"""Small HTTP client used by the TrendForge Streamlit frontend."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

import requests


@dataclass(slots=True)
class ApiError(RuntimeError):
    """Normalized backend error safe for presentation in the UI."""

    message: str
    status_code: int | None = None
    detail: Any = None
    url: str | None = None

    def __str__(self) -> str:
        prefix = f"HTTP {self.status_code}: " if self.status_code else ""
        return f"{prefix}{self.message}"


class TrendForgeApi:
    """HTTP boundary between the Streamlit UI and canonical FastAPI app."""

    ADMIN_HEADER = "X-TrendForge-Admin-Key"

    def __init__(
        self,
        base_url: str,
        admin_key: str | None = None,
        *,
        session: requests.Session | None = None,
        default_timeout: float = 30.0,
    ) -> None:
        normalized = str(base_url or "").strip().rstrip("/")
        if not normalized:
            raise ValueError("TrendForge API URL is required")
        if not normalized.startswith(("http://", "https://")):
            normalized = f"http://{normalized}"
        self.base_url = normalized
        self.admin_key = str(admin_key or "").strip()
        self.session = session or requests.Session()
        self.default_timeout = float(default_timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.admin_key:
            headers[self.ADMIN_HEADER] = self.admin_key
        return headers

    def _url(self, path: str) -> str:
        normalized_path = "/" + str(path or "").lstrip("/")
        return f"{self.base_url}{normalized_path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        files: Any = None,
        data: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> requests.Response:
        url = self._url(path)
        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json,
                files=files,
                data=data,
                headers=self._headers(),
                timeout=timeout or self.default_timeout,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise ApiError(
                message="TrendForge API is unreachable",
            ) from None

        if 300 <= response.status_code < 400:
            raise ApiError(
                message="TrendForge API returned an unexpected redirect",
                status_code=response.status_code,
            )

        if response.ok:
            return response

        detail: Any = None
        payload: Any = None
        message = "TrendForge API request failed"
        try:
            payload = response.json()
            detail = (
                payload.get("detail", payload) if isinstance(payload, dict) else payload
            )
            if isinstance(detail, str) and detail.strip():
                message = detail.strip()
            elif isinstance(detail, dict):
                candidate = detail.get("message") or detail.get("error")
                if candidate:
                    message = str(candidate)
        except (ValueError, RecursionError):
            # Gateway bodies and transport URLs may contain credentials.
            detail = None

        if response.status_code >= 500:
            message = "TrendForge API is temporarily unavailable"
            detail = None
            if isinstance(payload, dict):
                storage_block = (
                    "Administrative writes are disabled because "
                    "database storage is not verified persistent."
                )
                if payload.get("detail") == storage_block:
                    message = detail = storage_block
                else:
                    safe_detail = {}
                    reference = payload.get("reference")
                    if isinstance(reference, str) and re.fullmatch(
                        r"[0-9a-f]{12}", reference
                    ):
                        safe_detail["reference"] = reference
                    code = payload.get("error_code")
                    if isinstance(code, str) and code in {
                        "SERVICE_UNAVAILABLE",
                        "SCANNER_READ_UNAVAILABLE",
                        "INTERNAL_ERROR",
                    }:
                        safe_detail["error_code"] = code
                    detail = safe_detail or None

        raise ApiError(
            message=message,
            status_code=response.status_code,
            detail=detail,
        )

    @staticmethod
    def _json_response(
        response: requests.Response, *, object_only: bool = False
    ) -> Any:
        try:
            payload = response.json()
            # JSON's non-finite extensions cannot become financial figures.
            json.dumps(payload, allow_nan=False)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise ApiError(
                message="TrendForge API returned invalid JSON",
                status_code=response.status_code,
            ) from None
        if object_only and not isinstance(payload, dict):
            raise ApiError(
                message="TrendForge API returned a non-object JSON response",
                status_code=response.status_code,
            )
        return payload

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request("GET", path, params=params, timeout=timeout)
        return self._json_response(response, object_only=True)

    def post_json(
        self,
        path: str,
        payload: Mapping[str, Any] | None = None,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            path,
            params=params,
            json=dict(payload or {}),
            timeout=timeout,
        )
        result = self._json_response(response)
        return result if isinstance(result, dict) else {"result": result}

    def put_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request("PUT", path, json=dict(payload), timeout=timeout)
        result = self._json_response(response)
        return result if isinstance(result, dict) else {"result": result}

    def delete_json(
        self,
        path: str,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            "DELETE",
            path,
            timeout=timeout,
        )
        result = self._json_response(response)
        return result if isinstance(result, dict) else {"result": result}

    def get_bytes(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> bytes:
        return self._request("GET", path, params=params, timeout=timeout).content

    def upload_file(
        self,
        path: str,
        *,
        filename: str,
        file_obj: BinaryIO,
        content_type: str,
        form: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        files = {"file": (filename, file_obj, content_type)}
        response = self._request(
            "POST",
            path,
            files=files,
            data=dict(form or {}),
            timeout=timeout,
        )
        result = self._json_response(response)
        return result if isinstance(result, dict) else {"result": result}
