"""Small HTTP client used by the TrendForge Streamlit frontend."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, BinaryIO, Mapping

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
            )
        except requests.RequestException as exc:
            raise ApiError(
                message="TrendForge API is unreachable",
                detail=str(exc),
                url=url,
            ) from exc

        if response.ok:
            return response

        detail: Any = None
        message = response.reason or "TrendForge API request failed"
        try:
            payload = response.json()
            detail = payload.get("detail", payload) if isinstance(payload, dict) else payload
            if isinstance(detail, str) and detail.strip():
                message = detail.strip()
            elif isinstance(detail, dict):
                candidate = detail.get("message") or detail.get("error")
                if candidate:
                    message = str(candidate)
        except ValueError:
            if response.text.strip():
                detail = response.text.strip()

        raise ApiError(
            message=message,
            status_code=response.status_code,
            detail=detail,
            url=url,
        )

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request("GET", path, params=params, timeout=timeout)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ApiError(
                message="TrendForge API returned a non-object JSON response",
                status_code=response.status_code,
                detail=payload,
                url=response.url,
            )
        return payload

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
        result = response.json()
        return result if isinstance(result, dict) else {"result": result}

    def put_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        response = self._request("PUT", path, json=dict(payload), timeout=timeout)
        result = response.json()
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
        result = response.json()
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
        result = response.json()
        return result if isinstance(result, dict) else {"result": result}
