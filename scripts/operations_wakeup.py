"""Wake TrendForge and evaluate one expected market-day operation.

This client uses only the Python standard library so it can run in a minimal
external scheduler such as GitHub Actions. Secrets are read from environment
and are never printed.
"""
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
ENDPOINT = "/operations/external-tick"
RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}


class WakeupError(RuntimeError):
    pass


class MissedWindowError(WakeupError):
    pass


def target_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WakeupError(
            f"{URL_ENV} must be an absolute http(s) URL"
        )
    if parsed.username or parsed.password:
        raise WakeupError(
            f"{URL_ENV} must not contain embedded credentials"
        )
    if parsed.query or parsed.fragment:
        raise WakeupError(
            f"{URL_ENV} must not contain a query or fragment"
        )
    return value + ENDPOINT


def configured_key(value: str) -> str:
    key = str(value or "").strip()
    if len(key) < 32:
        raise WakeupError(
            f"{KEY_ENV} must contain at least 32 characters"
        )
    return key


def _decode_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WakeupError(
            "Scheduler endpoint returned invalid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise WakeupError(
            "Scheduler endpoint returned a non-object payload"
        )
    return payload


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
            "User-Agent": "TrendForge-R69.1-External-Scheduler",
        },
    )
    with opener(
        request,
        timeout=timeout,
    ) as response:
        status = int(
            getattr(response, "status", 200)
        )
        raw = response.read()
    if status < 200 or status >= 300:
        raise WakeupError(
            f"Scheduler endpoint returned HTTP {status}"
        )
    return _decode_response(raw)


def outcome(
    payload: dict[str, Any],
    *,
    expected_operation: str,
) -> tuple[str, str]:
    if payload.get("expected_operation") != expected_operation:
        raise WakeupError(
            "Scheduler response expected_operation mismatch"
        )

    after = payload.get("after")
    if not isinstance(after, dict):
        raise WakeupError(
            "Scheduler response is missing after contract"
        )
    status = str(after.get("status") or "")
    reason = str(after.get("reason") or "")

    if status in {"satisfied", "not_required"}:
        return status, reason
    if status == "missed_window":
        raise MissedWindowError(
            f"{expected_operation} missed its execution window: {reason}"
        )
    if status in {"due", "pending"}:
        return "retry", reason or status

    raise WakeupError(
        f"Unexpected scheduler contract status: {status or 'missing'}"
    )


def wake(
    *,
    base_url: str,
    key: str,
    expected_operation: str,
    attempts: int = 3,
    timeout: float = 75.0,
    base_delay: float = 10.0,
    opener: Callable[..., Any] = urlopen,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    operation = str(expected_operation or "").strip().lower()
    if operation not in {"morning", "eod"}:
        raise WakeupError(
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
            state, reason = outcome(
                payload,
                expected_operation=operation,
            )
            if state != "retry":
                return {
                    "status": state,
                    "reason": reason,
                    "expected_operation": operation,
                    "attempt": attempt,
                    "tick_status": (
                        payload.get("tick", {}).get("status")
                        if isinstance(
                            payload.get("tick"),
                            dict,
                        )
                        else None
                    ),
                }
            last_error = WakeupError(
                f"{operation} contract is {reason or state}"
            )
        except MissedWindowError:
            raise
        except HTTPError as exc:
            detail = ""
            try:
                detail_payload = _decode_response(
                    exc.read()
                )
                detail = str(
                    detail_payload.get("detail") or ""
                )
            except Exception:
                detail = ""
            message = (
                f"HTTP {exc.code}"
                + (f": {detail}" if detail else "")
            )
            last_error = WakeupError(message)
            if exc.code not in RETRYABLE_HTTP:
                raise last_error from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_error = WakeupError(
                f"Scheduler request failed: {type(exc).__name__}: {exc}"
            )
        except WakeupError as exc:
            last_error = exc

        if attempt < count:
            sleeper(delay * attempt)

    raise WakeupError(
        str(last_error or "External scheduler wake-up failed")
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description=(
            "Wake TrendForge and verify an expected "
            "morning/EOD operation."
        )
    )
    value.add_argument(
        "--expect",
        required=True,
        choices=("morning", "eod"),
    )
    value.add_argument(
        "--attempts",
        type=int,
        default=3,
    )
    value.add_argument(
        "--timeout",
        type=float,
        default=75.0,
    )
    value.add_argument(
        "--base-delay",
        type=float,
        default=10.0,
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = wake(
            base_url=os.getenv(URL_ENV, ""),
            key=os.getenv(KEY_ENV, ""),
            expected_operation=args.expect,
            attempts=args.attempts,
            timeout=args.timeout,
            base_delay=args.base_delay,
        )
    except MissedWindowError as exc:
        print(
            json.dumps(
                {
                    "status": "missed_window",
                    "expected_operation": args.expect,
                    "error": str(exc),
                },
                sort_keys=True,
            )
        )
        return 2
    except WakeupError as exc:
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

    print(
        json.dumps(
            result,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
