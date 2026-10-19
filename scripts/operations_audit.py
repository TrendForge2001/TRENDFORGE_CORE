"""Verify a TrendForge morning/EOD operation after its execution window."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


URL_ENV = "TRENDFORGE_SCHEDULER_URL"
KEY_ENV = "TRENDFORGE_SCHEDULER_API_KEY"
HEADER = "X-TrendForge-Scheduler-Key"
ENDPOINT = "/operations/external-audit"
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class AuditClientError(RuntimeError):
    pass


def target_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AuditClientError(
            f"{URL_ENV} must be an absolute http(s) URL"
        )
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if (
        parsed.scheme != "https"
        and parsed.hostname not in local_hosts
    ):
        raise AuditClientError(
            f"{URL_ENV} must use HTTPS outside localhost"
        )
    if parsed.username or parsed.password:
        raise AuditClientError(
            f"{URL_ENV} must not contain embedded credentials"
        )
    if parsed.query or parsed.fragment:
        raise AuditClientError(
            f"{URL_ENV} must not contain a query or fragment"
        )
    return value + ENDPOINT


def configured_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) < 32:
        raise AuditClientError(
            f"{KEY_ENV} must contain at least 32 characters"
        )
    return key


def _decode(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditClientError(
            "Audit endpoint returned invalid JSON"
        ) from exc
    if not isinstance(value, dict):
        raise AuditClientError(
            "Audit endpoint returned a non-object payload"
        )
    return value


def call_once(
    *,
    url: str,
    key: str,
    expected_operation: str,
    timeout: float,
    opener: Callable[..., Any] = urlopen,
) -> dict[str, Any]:
    body = json.dumps(
        {
            "expected_operation": expected_operation,
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            HEADER: key,
            "User-Agent": "TrendForge-R70.1-Operations-Audit",
        },
    )
    with opener(
        request,
        timeout=timeout,
    ) as response:
        status = int(getattr(response, "status", 200))
        raw = response.read()
    if status < 200 or status >= 300:
        raise AuditClientError(
            f"Audit endpoint returned HTTP {status}"
        )
    return _decode(raw)


def validate_result(
    payload: dict[str, Any],
    *,
    expected_operation: str,
) -> tuple[str, str]:
    if payload.get("operation") != expected_operation:
        raise AuditClientError(
            "Audit response operation mismatch"
        )
    if payload.get("auth_scope") != "operations_external_tick_only":
        raise AuditClientError(
            "Audit response auth scope mismatch"
        )
    if payload.get("broker_orders_allowed") is not False:
        raise AuditClientError(
            "Audit response does not preserve broker-order safety"
        )

    status = str(payload.get("status") or "")
    audit = payload.get("audit")
    if not isinstance(audit, dict):
        raise AuditClientError(
            "Audit response is missing audit evidence"
        )
    reason = str(audit.get("reason") or "")

    if status in {"healthy", "not_required"}:
        return status, reason
    if status in {"pending", "due", "disabled"}:
        return "not_final", reason or status
    if status in {
        "missed",
        "degraded",
        "configuration_error",
    }:
        raise AuditClientError(
            f"{expected_operation} reliability audit failed: "
            f"{status} ({reason})"
        )

    raise AuditClientError(
        f"Unexpected audit status: {status or 'missing'}"
    )


def audit(
    *,
    base_url: str,
    key: str,
    expected_operation: str,
    attempts: int = 2,
    timeout: float = 90.0,
    base_delay: float = 10.0,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    operation = str(expected_operation or "").strip().lower()
    if operation not in {"morning", "eod"}:
        raise AuditClientError(
            "expected operation must be morning or eod"
        )

    url = target_url(base_url)
    secret = configured_key(key)
    count = max(1, min(int(attempts), 10))
    delay = max(0.0, float(base_delay))
    last_error: Exception | None = None

    for attempt in range(1, count + 1):
        try:
            payload = call_once(
                url=url,
                key=secret,
                expected_operation=operation,
                timeout=max(1.0, float(timeout)),
                opener=opener,
            )
            state, reason = validate_result(
                payload,
                expected_operation=operation,
            )
            return {
                "status": state,
                "reason": reason,
                "expected_operation": operation,
                "attempt": attempt,
                "alert_status": (
                    payload.get("alert", {}).get("status")
                    if isinstance(payload.get("alert"), dict)
                    else None
                ),
            }
        except HTTPError as exc:
            detail = ""
            try:
                detail_payload = _decode(exc.read())
                detail = str(
                    detail_payload.get("detail") or ""
                )
            except Exception:
                detail = ""
            last_error = AuditClientError(
                f"HTTP {exc.code}"
                + (f": {detail}" if detail else "")
            )
            if exc.code not in RETRYABLE_HTTP:
                raise last_error from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = AuditClientError(
                f"Audit request failed: {type(exc).__name__}: {exc}"
            )
        except AuditClientError as exc:
            last_error = exc
            # Reliability failures are deterministic; only transport/server
            # failures need another request.
            if any(
                marker in str(exc)
                for marker in (
                    "reliability audit failed",
                    "Unexpected audit status",
                    "operation mismatch",
                    "auth scope mismatch",
                    "broker-order safety",
                )
            ):
                raise

        if attempt < count:
            sleeper(delay * attempt)

    raise AuditClientError(
        str(last_error or "Operations audit failed")
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Verify a TrendForge morning/EOD operation "
            "after its execution window."
        )
    )
    value.add_argument(
        "--expect",
        required=True,
        choices=("morning", "eod"),
    )
    value.add_argument("--attempts", type=int, default=2)
    value.add_argument("--timeout", type=float, default=90.0)
    value.add_argument("--base-delay", type=float, default=10.0)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = audit(
            base_url=os.getenv(URL_ENV, ""),
            key=os.getenv(KEY_ENV, ""),
            expected_operation=args.expect,
            attempts=args.attempts,
            timeout=args.timeout,
            base_delay=args.base_delay,
        )
    except AuditClientError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "expected_operation": args.expect,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
