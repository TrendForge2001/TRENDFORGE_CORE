"""Shared HTTP client for TrendForge providers."""
from __future__ import annotations

import logging
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15
RATE_LIMIT_DELAY = 0.50
CACHE_DIR = Path("cache/http")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/137.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/137.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/137.0 Safari/537.36",
]


class HTTPClient:
    """Reusable HTTP client with retry, timeout and request metrics."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout
        self.request_count = 0
        self.failed_requests = 0
        self.total_time = 0.0
        self.last_request: datetime | None = None
        self.session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET", "POST"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json,text/html,*/*",
            "Connection": "keep-alive",
        }

    def get(self, url: str, params: dict[str, Any] | None = None) -> requests.Response:
        return self._request("GET", url, params=params)

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> requests.Response:
        return self._request("POST", url, json=json, data=data)

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        start = time.monotonic()
        try:
            if RATE_LIMIT_DELAY:
                time.sleep(RATE_LIMIT_DELAY)
            response = self.session.request(
                method,
                url,
                headers=self.headers(),
                timeout=self.timeout,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except Exception:
            self.failed_requests += 1
            logger.exception("HTTP request failed: %s %s", method, url)
            raise
        finally:
            self.request_count += 1
            self.last_request = datetime.now()
            self.total_time += time.monotonic() - start

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        value = self.get(url, params=params).json()
        return value if isinstance(value, dict) else {"data": value}

    def get_text(self, url: str) -> str:
        return self.get(url).text

    def health(self) -> dict[str, Any]:
        return {
            "requests": self.request_count,
            "failed": self.failed_requests,
            "average_time": round(self.total_time / max(self.request_count, 1), 3),
            "last_request": self.last_request,
        }

    def reset_metrics(self) -> None:
        self.request_count = 0
        self.failed_requests = 0
        self.total_time = 0.0
        self.last_request = None
